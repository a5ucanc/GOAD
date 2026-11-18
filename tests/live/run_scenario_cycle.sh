#!/usr/bin/env bash
# Live disable proof for one scenario on a provisioned -Base instance.
# Usage: tests/live/run_scenario_cycle.sh <instance id> <scenario> [host]
# Steps: snapshot -> uninstall on a clean lab -> snapshot (no diff) -> enable_scenario ->
#        install again -> [VERIFY_CMD] -> disable_scenario -> snapshot (no diff) -> uninstall again.
# Set VERIFY_CMD to run a command between enable and disable (it gets SCN_TARGET).
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
export PATH="$HOME/.goad/.venv/bin:$PATH"
INSTANCE=$1; SCENARIO=$2; HOST=${3:-}
WS="$ROOT/workspace/$INSTANCE"
LAB=$(python3 -c "import json;print(json.load(open('$WS/instance.json'))['lab'])")
OUT="$ROOT/.superpowers/live/$INSTANCE/$SCENARIO"
mkdir -p "$OUT"
INV=(-i "$ROOT/ad/$LAB/data/inventory" -i "$WS/inventory_disable_vagrant" -i "$ROOT/globalsettings.ini")
FAIL=0
step() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; FAIL=1; fi; }

snapshot() {  # $1 = label
    ANSIBLE_LOAD_CALLBACK_PLUGINS=1 ANSIBLE_STDOUT_CALLBACK=json ansible domain "${INV[@]}" -m ansible.windows.win_powershell \
        -a "script={{ lookup('file', '$ROOT/scripts/scenario_snapshot.ps1') }}" > "$OUT/$1.json" 2>"$OUT/$1.err"
    python3 - "$OUT/$1.json" "$OUT/$1.txt" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
lines = []
for play in data["plays"]:
    for task in play["tasks"]:
        for host, res in sorted(task["hosts"].items()):
            if res.get("failed") or res.get("unreachable"):
                lines.append(f"{host} SNAPSHOT FAILED {res.get('msg', '')}")
            for line in res.get("output", []):
                lines.append(f"{host} {line}")
open(sys.argv[2], "w").write("\n".join(lines) + "\n")
PY
}

target() {
    python3 -c "
import json
for e in json.load(open('$WS/instance.json'))['scenarios']:
    if e['name'] == '$SCENARIO': print(e['target'] + ' ' + e['status'])"
}

playbook() {  # $1 = install|uninstall, $2 = target host
    printf "[scenario_target]\n%s\n\n[all:vars]\nscenario_name=%s\nscenario_target=%s\n" "$2" "$SCENARIO" "$2" > "$OUT/run_inventory"
    (cd "$ROOT/ansible" && ansible-playbook "${INV[@]}" -i "$OUT/run_inventory" "$ROOT/scenarios/$SCENARIO/ansible/$1.yml") > "$OUT/$1-$3.log" 2>&1
}

console() {
    printf 'load %s\n%s\nexit\n' "$INSTANCE" "$1" | (cd "$ROOT" && python goad.py) > "$OUT/console-$2.log" 2>&1
}

# resolve the target the engine would pick, through a dry enable check
GUESS=$(python3 - "$ROOT" "$LAB" "$SCENARIO" "$HOST" <<'PY'
import sys, os
sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1])
from goad.labs import Lab
lab = Lab.__new__(Lab)
lab.lab_name = sys.argv[2]; lab.capabilities = None; lab.dcs = []; lab.root_dc = ''; lab.host_domains = {}; lab._scenario_resolver = None
lab._load_lab_config(sys.argv[2])
s = lab.get_scenario_resolver().scenarios.get(sys.argv[3])
r = lab.get_scenario_resolver()
print(r.resolve_target(s, sys.argv[4] or None))
PY
)
echo "scenario $SCENARIO on $GUESS ($LAB, $INSTANCE)"

snapshot base
grep -q "SNAPSHOT FAILED" "$OUT/base.txt"; step "snapshot base" $((1 - $?))
playbook uninstall "$GUESS" clean; step "uninstall on a clean lab" $?
snapshot after-clean-uninstall
diff "$OUT/base.txt" "$OUT/after-clean-uninstall.txt" > "$OUT/diff-clean.txt"; step "no change from uninstall on a clean lab" $?
console "enable_scenario $SCENARIO $HOST" enable
read -r T S <<< "$(target)"; [ "$T" = "$GUESS" ] && [ "$S" = enabled ]; step "enable_scenario" $?
playbook install "$GUESS" again; step "install twice" $?
snapshot enabled
if [ -n "${VERIFY_CMD:-}" ]; then SCN_TARGET=$GUESS bash -c "$VERIFY_CMD" > "$OUT/verify.log" 2>&1; step "verify" $?; fi
console "disable_scenario $SCENARIO $GUESS" disable
[ -z "$(target)" ]; step "disable_scenario" $?
snapshot after-disable
diff "$OUT/base.txt" "$OUT/after-disable.txt" > "$OUT/diff-disable.txt"; step "no residue after disable" $?
playbook uninstall "$GUESS" twice; step "uninstall twice" $?
[ $FAIL = 0 ] && echo "RESULT PASS $SCENARIO" || echo "RESULT FAIL $SCENARIO (details in $OUT)"
exit $FAIL
