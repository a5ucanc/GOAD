#!/bin/bash
# Run an ansible playbook detached from the ssh session on the jumpbox and stream its log.
# usage : run_playbook_detached.sh <token> <playbook> <ansible-playbook args...>
# - same token + playbook still running   : re-attach to the log (the ssh session was dropped)
# - same token + playbook finished        : return its exit code
# - new token                             : start a new run
# The exit code of this script is the exit code of ansible-playbook.
TOKEN="$1"; shift
PLAYBOOK="$1"; shift
ID=$(echo "$PLAYBOOK" | tr '/.' '__')
LOG="/tmp/goad_${ID}.log"
RC="/tmp/goad_${ID}.rc"
PIDF="/tmp/goad_${ID}.pid"
TOKENF="/tmp/goad_${ID}.token"

running=0
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
    running=1
fi
same_token=0
if [ -f "$TOKENF" ] && [ "$(cat "$TOKENF")" = "$TOKEN" ]; then
    same_token=1
fi

if [ $running -eq 1 ]; then
    # a run of this playbook is still going (the previous ssh session was dropped) : follow it, never restart it
    echo "[*] playbook $PLAYBOOK still running on the jumpbox (pid $(cat "$PIDF")), re-attaching to $LOG"
    echo "$TOKEN" > "$TOKENF"
elif [ $running -eq 0 ] && [ $same_token -eq 1 ] && [ -f "$RC" ]; then
    echo "[*] playbook $PLAYBOOK already finished on the jumpbox with rc=$(cat "$RC")"
    tail -n 30 "$LOG"
    exit "$(cat "$RC")"
else
    rm -f "$RC" "$LOG"
    echo "$TOKEN" > "$TOKENF"
    nohup bash -c "/home/vagrant/.local/bin/ansible-playbook $* > '$LOG' 2>&1; echo \$? > '$RC'" > /dev/null 2>&1 &
    echo $! > "$PIDF"
    sleep 1
fi

tail -n +1 -f "$LOG" --pid="$(cat "$PIDF")"
sleep 1
if [ -f "$RC" ]; then
    exit "$(cat "$RC")"
fi
echo "[-] no exit code found for $PLAYBOOK (log : $LOG)"
exit 1
