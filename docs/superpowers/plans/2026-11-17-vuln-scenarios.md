# Toggleable Vulnerability Scenarios + Kali Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scenario mechanism that toggles vulnerabilities on and off on a live lab, hardened `-Base` labs derived from the GOAD family, five sample scenarios, and a non-domain Kali extension.

**Architecture:** A `Scenario` model and a pure-Python resolver in `goad/` decide availability (capabilities, depends, conflicts, per-host `touches`) and order. Instance state lives in `instance.json`. Scenario playbooks run through the existing Ansible provisioner with the `inventory_disable_vagrant` inventory plus a generated per-run inventory that carries `scenario_target` / `scenario_name`. Hardening and setting-scenario uninstalls share one Ansible role, `base_setting`, keyed by setting name.

**Tech Stack:** Python 3.8+ (`goad` CLI, `cmd`-based), Jinja2, Ansible (`ansible.windows`, `community.windows`), Vagrant (VirtualBox, VMware), pytest (new dev dependency).

**Spec:** `docs/superpowers/specs/2026-11-17-vuln-scenarios-design.md`

## Global Constraints

- Existing labs (`ad/GOAD`, `ad/GOAD-Light`, `ad/GOAD-Mini`, `ad/NHA`, `ad/DRACARYS`, `ad/SCCM`, `ad/MINILAB`) and existing extensions stay byte-identical.
- New labs: `ad/GOAD-Base`, `ad/GOAD-Light-Base`, `ad/GOAD-Mini-Base`.
- Every domain account, every `domain_password`, every `local_admin_password` and every password in `inventory_disable_vagrant` is `Aa1234567890!`. Scenario-owned accounts use it too.
- Scenarios never merge into `lab`; they read their own `data/vars.yml`.
- Scenario identity is `name@target`. `touches` overlap is a conflict only on the same target host.
- Scenario provisioning uses `inventory_disable_vagrant` (`administrator@<domain>` / `Aa1234567890!`).
- Scenarios are only offered on labs whose `config.json` declares `lab.capabilities`.
- Kali: Vagrant only (`virtualbox`, `vmware`), box `kalilinux/rolling`, IP `{{ip_range}}.99`, 2 CPU, 4096 MB, ssh forward host port 2299.
- Python must stay 3.8-compatible (no `match`, no `X | Y` type unions at runtime).

## Review Focus

1. `instance.json` written by the current GOAD (no `scenarios` key) must still load; tested in Task 3 (`test_load_legacy_instance_without_scenarios`).
2. Enabling a scenario on a non-`-Base` lab must refuse with a clear reason, not crash on a missing `capabilities` key; tested in Task 2 (`test_lab_without_capabilities_offers_nothing`).
3. A scenario folder with a malformed or missing `scenario.json` must be skipped with a warning, not break `goad` startup; tested in Task 1 (`test_registry_skips_invalid_scenario`).
4. A user naming a target host not in the capability list (typo, wrong lab) must be refused before Ansible runs; tested in Task 2 (`test_target_not_in_capability_refused`).
5. `depends` cycles in scenario packages must be reported as an error, not recurse forever; tested in Task 2 (`test_install_order_cycle_raises`).

---

## Phase 1 — Engine, CLI, Kali

### Task 1: Test harness, paths and `Scenario` model

**Files:**
- Modify: `pyproject.toml` (add `[tool.poetry.group.dev.dependencies] pytest = "^8.0"`)
- Create: `tests/__init__.py`, `tests/conftest.py`
- Modify: `goad/goadpath.py` (append scenario section after the EXTENSIONS section)
- Create: `goad/scenario.py`
- Create: `scenarios/.gitkeep`
- Test: `tests/test_scenario.py`

**Interfaces:**
- Produces:
  - `GoadPath.get_scenarios_path() -> str` (`<project>/scenarios`)
  - `GoadPath.get_scenario_path(name: str) -> str` (trailing `sep`)
  - `GoadPath.get_scenario_config_file(name: str) -> str` (`.../scenario.json`)
  - `GoadPath.get_scenario_ansible_path(name: str) -> str` (`.../ansible`, no trailing sep, same as extensions)
  - `class Scenario` with attributes `name: str`, `description: str`, `type: str` (`"object"|"setting"`), `requires: list[str]`, `target: str` (`""` = domain-wide), `depends: list[str]`, `conflicts: list[str]`, `touches: list[str]`, `labs: list[str]`; constructor `Scenario(name: str, data: dict)`; classmethod `Scenario.from_file(name: str, path: str) -> Scenario`; `get_playbook(install: bool) -> str` returning `install.yml` / `uninstall.yml`; `get_ansible_path() -> str`; `allowed_on_lab(lab_name: str) -> bool`.
  - `class InvalidScenario(Exception)` in `goad/scenario.py`.
  - `class Scenarios` with `__init__(self, scenarios_path: str)`, `get(name: str) -> Scenario | None`, `all() -> list[Scenario]`.
- `tests/conftest.py` fixture `scenario_dir(tmp_path)` returning a helper `make(name: str, **fields) -> str` that writes `<tmp>/<name>/scenario.json` with defaults `{"description": "d", "type": "object", "requires": [], "target": "", "depends": [], "conflicts": [], "touches": [], "labs": ["*"]}` merged with `fields`.

- [ ] **Step 1: Add pytest and write failing tests**

`tests/test_scenario.py`:

```python
from goad.scenario import Scenario, Scenarios, InvalidScenario
import pytest

def test_from_file_loads_fields(scenario_dir):
    path = scenario_dir.make("esc8", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    s = Scenario.from_file("esc8", path)
    assert s.type == "setting"
    assert s.requires == ["adcs"]
    assert s.target == "adcs"
    assert s.touches == ["adcs.web_enrollment"]
    assert s.get_playbook(True) == "install.yml"
    assert s.get_playbook(False) == "uninstall.yml"

def test_invalid_type_rejected():
    with pytest.raises(InvalidScenario):
        Scenario("x", {"description": "d", "type": "bogus"})

def test_missing_optional_fields_default_empty():
    s = Scenario("x", {"description": "d", "type": "object"})
    assert s.requires == [] and s.depends == [] and s.target == "" and s.labs == ["*"]

def test_allowed_on_lab():
    assert Scenario("x", {"description": "d", "type": "object", "labs": ["GOAD-Base"]}).allowed_on_lab("GOAD-Base")
    assert not Scenario("x", {"description": "d", "type": "object", "labs": ["GOAD-Base"]}).allowed_on_lab("GOAD-Mini-Base")

def test_registry_skips_invalid_scenario(scenario_dir, tmp_path):
    scenario_dir.make("good")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "scenario.json").write_text("{not json")
    (tmp_path / "empty").mkdir()
    reg = Scenarios(str(tmp_path))
    assert [s.name for s in reg.all()] == ["good"]
    assert reg.get("broken") is None
```

- [ ] **Step 2: Run tests, expect failure**

Run: `poetry install --with dev && poetry run pytest tests/test_scenario.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'goad.scenario'`

- [ ] **Step 3: Implement `goad/scenario.py` and the `GoadPath` methods**

`type` must be `object` or `setting`, and `description` is required, otherwise raise `InvalidScenario`. `Scenarios` iterates `Utils.list_folders(path)`, catches `InvalidScenario`, `json.JSONDecodeError` and `FileNotFoundError`, and logs `Log.warning(f'scenario {name} skipped: {e}')`. Order `all()` by name.

- [ ] **Step 4: Run tests, expect pass**

Run: `poetry run pytest tests/test_scenario.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml poetry.lock tests goad/scenario.py goad/goadpath.py scenarios/.gitkeep
git commit -m "feat(scenarios): scenario model, registry and paths"
```

### Task 2: Resolver

**Files:**
- Create: `goad/scenario_resolver.py`
- Test: `tests/test_scenario_resolver.py`

**Interfaces:**
- Consumes: `Scenario`, `Scenarios` (Task 1).
- Produces:
  - `@dataclass EnabledScenario(name: str, target: str, enabled_at: str, status: str = "enabled")`; `status` is `"enabled"` or `"dirty"`; property `key -> str` returning `f"{name}@{target}"`.
  - `class ScenarioResolver(scenarios: Scenarios, lab_name: str, capabilities: dict[str, list[str]] | None, root_dc: str, dcs: list[str])`
    - `resolve_target(scenario: Scenario, host: str | None) -> str`; raises `ScenarioRefused`.
    - `check_enable(name: str, host: str | None, enabled: list[EnabledScenario]) -> str` returns the resolved target, or raises `ScenarioRefused(reasons: list[str])`.
    - `available(enabled: list[EnabledScenario]) -> list[tuple[Scenario, list[str]]]` returns every scenario with its refusal reasons (empty list = available), computed with `host=None`.
    - `install_order(names: list[str]) -> list[str]` returns a topological order over `depends`; raises `ScenarioRefused` on a cycle or unknown name.
    - `dependents(name: str, enabled: list[EnabledScenario]) -> list[EnabledScenario]` returns enabled scenarios whose `depends` includes `name`, transitively, in disable order (deepest first).
  - `class ScenarioRefused(Exception)` with attribute `reasons: list[str]`.

Rules for `check_enable`, all reasons collected:
1. `capabilities is None` gives `"lab <lab> does not support scenarios"` (return immediately).
2. Unknown name gives `"unknown scenario <name>"` (return immediately).
3. `not allowed_on_lab` gives `"not available for lab <lab>"`.
4. Each missing capability in `requires` gives `"missing capability <cap>"`.
5. Target: capability target means `host` must be in `capabilities[target]`, default is first entry. Empty target means `host` must be in `dcs`, default is `root_dc`. Wrong host gives `"host <h> does not provide <cap>"` / `"host <h> is not a domain controller"`.
6. `name@target` already enabled gives `"already enabled on <target>"`.
7. Each `depends` entry with no enabled entry (any target) gives `"requires scenario <dep>"`.
8. Each enabled entry whose name is in `conflicts`, or whose scenario lists this name in its own `conflicts`, gives `"conflicts with <key>"`.
9. Each enabled entry on the same target sharing a `touches` key gives `"<key> already changes <setting> on <target>"`.

Dirty entries count as enabled for rules 6–9.

- [ ] **Step 1: Write failing tests**

Fixture: a `Scenarios` built in `tmp_path` with `kerberoast` (object, no target), `esc1` (object, requires adcs, target adcs), `esc8` (setting, requires adcs, target adcs, touches adcs.web_enrollment), `esc8-alt` (setting, same touches), `relay` (object, depends esc8), `relay2` (object, depends relay), `hardened-ca` (object, conflicts esc8). Resolver: lab `GOAD-Base`, capabilities `{"adcs": ["dc01", "srv03"], "mssql": ["srv02"]}`, root_dc `dc01`, dcs `["dc01","dc02","dc03"]`.

```python
def test_capability_target_defaults_to_first_host(resolver):
    assert resolver.check_enable("esc8", None, []) == "dc01"

def test_named_target_used(resolver):
    assert resolver.check_enable("esc8", "srv03", []) == "srv03"

def test_target_not_in_capability_refused(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("esc8", "srv02", [])
    assert "host srv02 does not provide adcs" in e.value.reasons

def test_domain_wide_defaults_to_root_dc(resolver):
    assert resolver.check_enable("kerberoast", None, []) == "dc01"
    assert resolver.check_enable("kerberoast", "dc03", []) == "dc03"

def test_missing_capability(resolver_no_adcs):
    with pytest.raises(ScenarioRefused) as e:
        resolver_no_adcs.check_enable("esc1", None, [])
    assert "missing capability adcs" in e.value.reasons

def test_lab_without_capabilities_offers_nothing(scenarios):
    r = ScenarioResolver(scenarios, "GOAD", None, "dc01", ["dc01"])
    assert all(reasons == ["lab GOAD does not support scenarios"] for _, reasons in r.available([]))

def test_touches_conflict_same_host_only(resolver):
    on = [EnabledScenario("esc8", "dc01", "t")]
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("esc8-alt", "dc01", on)
    assert "esc8@dc01 already changes adcs.web_enrollment on dc01" in e.value.reasons
    assert resolver.check_enable("esc8-alt", "srv03", on) == "srv03"

def test_same_scenario_two_targets(resolver):
    on = [EnabledScenario("esc8", "dc01", "t")]
    assert resolver.check_enable("esc8", "srv03", on) == "srv03"
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8", "dc01", on)

def test_conflicts_both_directions(resolver):
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("hardened-ca", None, [EnabledScenario("esc8", "dc01", "t")])
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8", "srv03", [EnabledScenario("hardened-ca", "dc01", "t")])

def test_depends_required(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("relay", None, [])
    assert "requires scenario esc8" in e.value.reasons

def test_dirty_still_conflicts(resolver):
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8-alt", "dc01", [EnabledScenario("esc8", "dc01", "t", "dirty")])

def test_install_order(resolver):
    assert resolver.install_order(["relay2", "esc8", "relay"]) == ["esc8", "relay", "relay2"]

def test_install_order_cycle_raises(cyclic_resolver):
    with pytest.raises(ScenarioRefused):
        cyclic_resolver.install_order(["a", "b"])

def test_dependents_deepest_first(resolver):
    on = [EnabledScenario("esc8", "dc01", "t"), EnabledScenario("relay", "dc01", "t"), EnabledScenario("relay2", "dc01", "t")]
    assert [e.name for e in resolver.dependents("esc8", on)] == ["relay2", "relay"]
```

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_scenario_resolver.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'goad.scenario_resolver'`

- [ ] **Step 3: Implement `goad/scenario_resolver.py`**

`install_order`: DFS with a visiting set for cycle detection. Include the `depends` of requested names only when they are in the requested list; dependencies already enabled are the caller's concern.

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest tests/test_scenario_resolver.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add goad/scenario_resolver.py tests/test_scenario_resolver.py
git commit -m "feat(scenarios): resolver for capabilities, depends, conflicts, touches"
```

### Task 3: Instance state and lab capabilities

**Files:**
- Modify: `goad/instance.py` (constructor, `save_json_instance`, new methods)
- Modify: `goad/instances.py:28-31` (read `scenarios` with default `[]`)
- Modify: `goad/labs.py` (`Lab` loads capabilities, DCs and scenarios)
- Test: `tests/test_instance_scenarios.py`

**Interfaces:**
- Consumes: `EnabledScenario`, `ScenarioResolver`, `Scenarios`.
- Produces:
  - `LabInstance.__init__(..., extensions=None, status='', default=False, scenarios=None)` where `scenarios` is a list of dicts from JSON, stored as `self.scenarios: list[EnabledScenario]`.
  - `LabInstance.add_scenario(name: str, target: str) -> None` (sets `enabled_at` to UTC ISO `YYYY-MM-DDTHH:MM:SSZ`, saves).
  - `LabInstance.remove_scenario(name: str, target: str) -> None` (saves).
  - `LabInstance.mark_scenario_dirty(name: str, target: str) -> None` (saves).
  - `instance.json` gains `"scenarios": [{"name", "target", "enabled_at", "status"}]`.
  - `Lab.capabilities: dict | None` read from `ad/<lab>/data/config.json` `lab.capabilities`, `None` if absent.
  - `Lab.dcs: list[str]` (host keys with `type == "dc"`), `Lab.root_dc: str` (DC of the first domain whose name has no parent among the other domains; for the GOAD family this is `dc01`).
  - `Lab.is_base() -> bool` returns `self.capabilities is not None`.
  - `Lab.get_scenario_resolver() -> ScenarioResolver` (registry from `GoadPath.get_scenarios_path()`, built once).
  - `Lab.get_scenario(name: str) -> Scenario | None`.

- [ ] **Step 1: Write failing tests**

```python
def test_load_legacy_instance_without_scenarios(tmp_workspace):
    # instance.json without "scenarios" key
    inst = load_instance(tmp_workspace, {"id": "x", "lab": "GOAD", "provider": "virtualbox", "provisioner": "local", "ip_range": "192.168.56", "extensions": [], "status": "ready", "is_default": False})
    assert inst.scenarios == []

def test_add_remove_dirty_roundtrip(tmp_instance):
    tmp_instance.add_scenario("esc8", "dc01")
    tmp_instance.mark_scenario_dirty("esc8", "dc01")
    data = json.load(open(tmp_instance.instance_path + "/instance.json"))
    assert data["scenarios"][0]["name"] == "esc8"
    assert data["scenarios"][0]["target"] == "dc01"
    assert data["scenarios"][0]["status"] == "dirty"
    tmp_instance.remove_scenario("esc8", "dc01")
    assert json.load(open(tmp_instance.instance_path + "/instance.json"))["scenarios"] == []

def test_lab_capabilities_and_root_dc(fake_lab_config):
    # config.json with capabilities, dc01 sevenkingdoms.local, dc02 north.sevenkingdoms.local, dc03 essos.local
    lab = build_lab(fake_lab_config)
    assert lab.is_base()
    assert lab.root_dc == "dc01"
    assert sorted(lab.dcs) == ["dc01", "dc02", "dc03"]

def test_lab_without_capabilities_is_not_base(fake_lab_config_no_caps):
    assert not build_lab(fake_lab_config_no_caps).is_base()
```

Fixtures monkeypatch `goad.goadpath.project_path` / `GoadPath.get_workspace_path` / `GoadPath.get_lab_data_path` to `tmp_path`. `build_lab` constructs `Lab` with provider loading stubbed via monkeypatching `Lab._load_providers` to a no-op.

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_instance_scenarios.py -v`
Expected: FAIL (`unexpected keyword argument 'scenarios'` / `AttributeError: 'Lab' object has no attribute 'is_base'`)

- [ ] **Step 3: Implement**

`Lab` reads `config.json` lazily in `__init__` with a `try/except FileNotFoundError` that leaves `capabilities=None`, `dcs=[]`, `root_dc=""`. `instances.py` uses `instance_info.get('scenarios', [])`.

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add goad/instance.py goad/instances.py goad/labs.py tests/test_instance_scenarios.py
git commit -m "feat(scenarios): persist scenario state and read lab capabilities"
```

### Task 4: Provisioner `run_scenario`

**Files:**
- Modify: `goad/provisioner/ansible/ansible.py` (new method after `run_extension`)
- Test: `tests/test_run_scenario.py`

**Interfaces:**
- Consumes: `Scenario.get_playbook`, `Scenario.get_ansible_path`, `get_disable_vagrant_inventory()`.
- Produces: `Ansible.run_scenario(scenario: Scenario, target: str, current_instance_extensions_name: list[str], install: bool = True) -> bool`.

Behaviour: write `<instance_path>/scenario_run_inventory` containing:

```ini
[all:vars]
scenario_name=<name>
scenario_target=<target>
```

Inventory order: `get_disable_vagrant_inventory()` result (lab, then global), then every enabled extension's `<ext>_inventory` that exists, then `scenario_run_inventory`. Call `self.run_playbook(scenario.get_playbook(install), inventory, playbook_path=scenario.get_ansible_path() + os.path.sep)`. This avoids changing the four `run_playbook` implementations.

- [ ] **Step 1: Write failing test**

```python
def test_run_scenario_inventory_and_playbook(tmp_path, monkeypatch, scenario_dir):
    calls = []
    prov = make_ansible_stub(tmp_path, run_playbook=lambda pb, inv, tries=3, timeout=30, playbook_path=None: calls.append((pb, inv, playbook_path)) or True)
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", [], install=False)
    pb, inv, path = calls[0]
    assert pb == "uninstall.yml"
    assert inv[0].endswith("inventory_disable_vagrant")
    assert inv[-1].endswith("scenario_run_inventory")
    content = open(inv[-1]).read()
    assert "scenario_name=esc8" in content and "scenario_target=srv03" in content
```

`make_ansible_stub` builds an `Ansible` subclass instance with `instance_path=str(tmp_path)`, creates an empty `inventory_disable_vagrant` file there, and stubs `_get_global_inventory` to return `None`.

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_run_scenario.py -v`
Expected: FAIL, `AttributeError: ... has no attribute 'run_scenario'`

- [ ] **Step 3: Implement `run_scenario`**

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add goad/provisioner/ansible/ansible.py tests/test_run_scenario.py
git commit -m "feat(scenarios): provisioner runs scenario playbooks with disable_vagrant inventory"
```

### Task 5: Scenario service and CLI commands

**Files:**
- Create: `goad/scenario_service.py`
- Modify: `goad.py` (new `do_list_scenarios`, `do_enable_scenario`, `do_disable_scenario`, `do_reset_scenarios`, `complete_enable_scenario`, `complete_disable_scenario`)
- Modify: `goad/menu.py` (scenarios block inside the instance-loaded section, after the extensions entries at lines 52-56)
- Test: `tests/test_scenario_service.py`

**Interfaces:**
- Consumes: `LabInstance` scenario methods, `Lab.get_scenario_resolver()`, `Lab.get_scenario()`, `Ansible.run_scenario`.
- Produces: `class ScenarioService(instance: LabInstance, lab: Lab, provisioner)` with:
  - `enable(name: str, host: str | None) -> bool`
  - `disable(name: str, host: str | None, cascade: bool = False) -> bool`
  - `reset() -> bool`
  - `reapply() -> bool` (re-runs `install.yml` for every enabled entry in `install_order`; used by Task 6)
  - `listing(show_all: bool) -> list[tuple[str, str, str]]` as `(name, state, detail)` rows, where state is `"enabled"`, `"dirty"`, `"available"` or `"unavailable"`. Enabled and dirty rows come first, with detail = target. Unavailable rows appear only when `show_all`, with detail = `"; ".join(reasons)`.

Behaviour:
- `enable`: `check_enable` (on refusal, log each reason with `Log.error` and return False), then `run_scenario(install=True)`. On success, `add_scenario`. On failure, run `run_scenario(install=False)` as best-effort cleanup, do not record state, and return False.
- `disable`: resolve the entry. If `host` is None and the name is enabled on more than one target, refuse with `"<name> is enabled on <t1>, <t2>: name the host"`. If enabled dependents exist and `cascade` is false, refuse and list them. With `cascade`, disable dependents first (from `dependents()`). For each entry run `run_scenario(install=False)`: on success `remove_scenario`; on failure `mark_scenario_dirty` and stop, returning False.
- `reset`: disable all entries in reverse `install_order`, stopping at the first failure.
- CLI arg parsing: `enable_scenario <name> [host]`, `disable_scenario <name> [host] [--cascade]`, `list_scenarios [all]`. Every command logs `Log.error('Scenarios can only be used from an instance')` when no instance is loaded. `list_scenarios` prints a `rich` table with columns `Scenario`, `State`, `Target / reason`.

- [ ] **Step 1: Write failing tests** (fake provisioner records calls and returns configurable results)

```python
def test_enable_records_state(svc, prov):
    assert svc.enable("esc8", None)
    assert prov.calls == [("esc8", "dc01", True)]
    assert [(e.name, e.target) for e in svc.instance.scenarios] == [("esc8", "dc01")]

def test_enable_refused_runs_nothing(svc, prov):
    assert not svc.enable("esc8", "srv02")
    assert prov.calls == []

def test_failed_install_cleans_up_and_records_nothing(svc, prov):
    prov.fail_on = {("esc8", True)}
    assert not svc.enable("esc8", None)
    assert prov.calls == [("esc8", "dc01", True), ("esc8", "dc01", False)]
    assert svc.instance.scenarios == []

def test_disable_requires_host_when_ambiguous(svc):
    svc.enable("esc8", "dc01"); svc.enable("esc8", "srv03")
    assert not svc.disable("esc8", None)
    assert svc.disable("esc8", "srv03")

def test_disable_blocked_by_dependents_without_cascade(svc):
    svc.enable("esc8", None); svc.enable("relay", None)
    assert not svc.disable("esc8", None)

def test_cascade_disables_dependents_first(svc, prov):
    svc.enable("esc8", None); svc.enable("relay", None); prov.calls.clear()
    assert svc.disable("esc8", None, cascade=True)
    assert [c[0] for c in prov.calls] == ["relay", "esc8"]

def test_failed_uninstall_marks_dirty_and_stops(svc, prov):
    svc.enable("esc8", None); svc.enable("relay", None)
    prov.fail_on = {("relay", False)}
    assert not svc.disable("esc8", None, cascade=True)
    states = {e.name: e.status for e in svc.instance.scenarios}
    assert states == {"esc8": "enabled", "relay": "dirty"}

def test_listing_hides_unavailable_unless_all(svc):
    names = [r[0] for r in svc.listing(False)]
    assert "unknown-cap-scenario" not in names
    assert "unknown-cap-scenario" in [r[0] for r in svc.listing(True)]
```

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_scenario_service.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'goad.scenario_service'`

- [ ] **Step 3: Implement `goad/scenario_service.py` and wire the CLI and menu in `goad.py` / `goad/menu.py`**

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 5: Smoke-check the CLI without a lab**

Run: `python3 goad.py -t list_scenarios` from the repo root.
Expected: `Scenarios can only be used from an instance` and exit without a traceback.

- [ ] **Step 6: Commit**

```bash
git add goad/scenario_service.py goad.py goad/menu.py tests/test_scenario_service.py
git commit -m "feat(scenarios): enable/disable/reset/list commands"
```

### Task 6: Base-lab provisioning hooks

**Files:**
- Modify: `goad.py` (`do_provision_lab` at line 142, `do_provision_lab_from` at line 151)
- Create: `goad/base_lab_flow.py`
- Test: `tests/test_base_lab_flow.py`

**Interfaces:**
- Consumes: `Lab.is_base()`, `LabInstance.status`, `ScenarioService.reapply()`, provisioner `run()`, `run_from(task)`, `run_disable_vagrant(disable_vagrant: bool)`.
- Produces: `provision_base_lab(instance, lab, provisioner, service, from_task: str | None = None) -> bool`.

Behaviour, in this order:
1. If `instance.status == READY` (the lab was provisioned before, so vagrant is already disabled), run `run_disable_vagrant(False)`, which re-enables vagrant. Abort with False on failure.
2. Run `provisioner.run()` or `provisioner.run_from(from_task)`. On failure, return False. Vagrant stays enabled so the user can retry.
3. Run `run_disable_vagrant(True)`. Abort on failure.
4. `service.reapply()`, and return its result.

`do_provision_lab` / `do_provision_lab_from` call `provision_base_lab` when `lab.is_base()`, otherwise they keep today's code path unchanged.

- [ ] **Step 1: Write failing tests**

```python
def test_first_provision_skips_enable_vagrant(fakes):
    fakes.instance.status = "created"
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["run", "disable_vagrant", "reapply"]

def test_reprovision_enables_vagrant_first(fakes):
    fakes.instance.status = READY
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "run", "disable_vagrant", "reapply"]

def test_run_from_used_when_task_given(fakes):
    fakes.instance.status = READY
    provision_base_lab(*fakes.args(), from_task="ad-data.yml")
    assert fakes.log[1] == "run_from:ad-data.yml"

def test_failed_run_leaves_vagrant_enabled(fakes):
    fakes.instance.status = READY; fakes.fail = "run"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "run"]
```

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_base_lab_flow.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement and wire into `goad.py`**

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add goad/base_lab_flow.py goad.py tests/test_base_lab_flow.py
git commit -m "feat(scenarios): base labs disable vagrant and reapply scenarios after provisioning"
```

### Task 7: Kali extension

**Files:**
- Create: `extensions/kali/extension.json`
- Create: `extensions/kali/inventory`
- Create: `extensions/kali/providers/virtualbox/Vagrantfile`, `extensions/kali/providers/vmware/Vagrantfile`
- Create: `extensions/kali/ansible/install.yml`, `extensions/kali/ansible/ansible.cfg` (copy of `extensions/lx01/ansible/ansible.cfg`)
- Create: `extensions/kali/README.md`

**Interfaces:**
- Consumes: the existing extension loader (`compatibility: ["*"]`), `lab` from `ansible/data.yml`.
- Produces: host `kali` in group `[extensions]` only.

Values:
- `extension.json`: `{"name": "kali", "description": "Add a Kali attacker box on the lab network (not domain joined)", "machines": ["kali"], "compatibility": ["*"], "impact": "none"}`
- Vagrantfile fragment (same shape as `extensions/lx01/providers/virtualbox/Vagrantfile`): `:name => "{{lab_name}}-KALI"`, `:ip => "{{ip_range}}.99"`, `:box => "kalilinux/rolling"`, `:os => "linux"`, `:cpus => 2`, `:mem => 4096`, `:forwarded_port => [ {:guest => 22, :host => 2299, :id => "ssh"} ]`.
- inventory: `kali ansible_host={{ip_range}}.99 dict_key=kali ansible_connection=ssh ansible_ssh_common_args='-o StrictHostKeyChecking=no'` under `[default]`, and `kali` under `[extensions]`.
- `install.yml` plays on `hosts: kali`, `become: yes`. It loads `lab` the way `extensions/lx01/ansible/install.yml` lines 1-6 do, but does **not** merge `lab_extension` (Kali has no `data/config.json`). It then:
  1. Builds the list of DC IPs: `hostvars[lab.domains[d].dc].ansible_host` for every domain `d`.
  2. Writes a NetworkManager drop-in `/etc/NetworkManager/conf.d/goad-dns.conf` plus a connection DNS override on the lab interface (the one holding `ansible_host`), so the DC IPs resolve first, then `dns_server_forwarder`. Restarts NetworkManager.
  3. Adds `/etc/hosts` lines `<ip> <hostname>.<domain> <hostname>` for every `lab.hosts` entry.
  4. Writes `/etc/krb5.conf` with one `[realms]` entry per domain (KDC = that domain's DC FQDN) and `dns_lookup_kdc = true`.
  5. Installs `kali-linux-default` with `apt` (`update_cache: yes`), only when `dpkg -s kali-linux-default` fails.

- [ ] **Step 1: Write the files**

- [ ] **Step 2: Syntax check**

Run: `cd extensions/kali/ansible && ansible-playbook --syntax-check -i localhost, install.yml`
Expected: `playbook: install.yml` with no error

- [ ] **Step 3: Loader check**

Run: `python3 -c "from goad.extension import Extension; e=Extension('kali'); print(e.is_available('GOAD-Mini-Base'), e.list_providers_name())"`
Expected: `True ['virtualbox', 'vmware']` (order may differ)

- [ ] **Step 4: Live check (after Task 9 delivers a lab, on VirtualBox)**

From a loaded `GOAD-Mini-Base` instance, run `install_extension kali`. Then from Kali: `nslookup kingslanding.sevenkingdoms.local` resolves to `.10`, `realm list` is empty (no domain join), and `impacket-GetADUsers -all -dc-ip <ip_range>.10 'sevenkingdoms.local/administrator:Aa1234567890!'` lists users.

- [ ] **Step 5: Commit**

```bash
git add extensions/kali
git commit -m "feat(extensions): kali attacker box, vagrant only, not domain joined"
```

## Phase 2 — Base labs and sample scenarios

### Task 8: `base_setting` role and hardening playbook

**Files:**
- Create: `ansible/roles/base_setting/tasks/main.yml` (dispatches `include_tasks: "{{ setting_key | replace('.', '_') }}.yml"`)
- Create: one task file per key, listed below
- Create: `ansible/hardening.yml`

**Interfaces:**
- Produces: role `base_setting` with vars `setting_key: str` and `setting_value: any`, run against a Windows host. Every task file must be idempotent and must handle every value listed for its key. Later tasks and scenarios include it as `include_role: name=base_setting` with these vars.
- `ansible/hardening.yml`: imports `data.yml`, then for each host in `domain` loops over `lab.base_settings[inventory_hostname] | dict2items` and includes `base_setting` with `setting_key=item.key`, `setting_value=item.value`.

Keys, with the hardened value first and other accepted values after:

| Key | Values | Implementation hint |
|-----|--------|---------------------|
| `net.llmnr` | `disabled`, `enabled` | `HKLM\Software\Policies\Microsoft\Windows NT\DNSClient\EnableMulticast` 0/1 (reuse `vulns/enable_llmnr` command) |
| `net.nbtns` | `disabled`, `enabled` | `NetbiosOptions` 2/0 on every `HKLM\SYSTEM\CurrentControlSet\Services\NetBT\Parameters\Interfaces\Tcpip_*` |
| `net.mdns` | `disabled`, `enabled` | `HKLM\SYSTEM\CurrentControlSet\Services\Dnscache\Parameters\EnableMDNS` 0/1 |
| `smb.signing` | `required`, `optional` | `LanmanServer` and `LanmanWorkstation` `RequireSecuritySignature` 1/0 |
| `ldap.signing` | `required`, `none` | DC only: `NTDS\Parameters\LDAPServerIntegrity` 2/1 |
| `ldap.channel_binding` | `always`, `never` | DC only: `NTDS\Parameters\LdapEnforceChannelBinding` 2/0 |
| `kerberos.rc4` | `disabled`, `enabled` | `...\Policies\System\Kerberos\Parameters\SupportedEncryptionTypes` `0x18`/`0x1C` |
| `ntlm.lmcompat` | `5`, `0`–`4` | `HKLM\SYSTEM\CurrentControlSet\Control\Lsa\LmCompatibilityLevel` |
| `defender.realtime` | `on`, `off` | reuse role `settings/windows_defender` with `windows_defender_status`; also set `SubmitSamplesConsent=2`, `MAPSReporting=0` |
| `firewall.state` | `on`, `off` | `win_firewall` all profiles |
| `dc.spooler` | `disabled`, `enabled` | `win_service Spooler` start_mode + state |
| `dc.strong_cert_binding` | `2`, `0`, `1` | `HKLM\SYSTEM\CurrentControlSet\Services\Kdc\StrongCertificateBindingEnforcement` |
| `adcs.web_enrollment` | `false`, `true` | true: `Install-WindowsFeature ADCS-Web-Enrollment` + `Install-AdcsWebEnrollment -Force`, and make sure IIS `/certsrv` accepts NTLM over HTTP with EPA off. false: `Uninstall-AdcsWebEnrollment -Force` + `Uninstall-WindowsFeature ADCS-Web-Enrollment` |
| `adcs.editf_san` | `off`, `on` | `certutil -setreg policy\EditFlags -/+EDITF_ATTRIBUTESUBJECTALTNAME2`, then restart `certsvc` |
| `adcs.enforce_encrypt` | `on`, `off` | `certutil -setreg CA\InterfaceFlags +/-IF_ENFORCEENCRYPTICERTREQUEST`, then restart `certsvc` |

ADCS keys run with the same `become`/`runas` vars as `ansible/roles/vulns/adcs_esc6/tasks/main.yml`. Registry keys need a reboot handler only where Windows requires one (LDAP signing does not; SMB signing does not).

- [ ] **Step 1: Write the role and `hardening.yml`**

- [ ] **Step 2: Syntax check**

Run: `cd ansible && ansible-playbook --syntax-check -i ../ad/GOAD-Mini/data/inventory hardening.yml`
Expected: `playbook: hardening.yml`

- [ ] **Step 3: Commit**

```bash
git add ansible/roles/base_setting ansible/hardening.yml
git commit -m "feat(base): base_setting role and hardening playbook"
```

Live verification of every key happens in Task 9 Step 5.

### Task 9: `GOAD-Mini-Base` lab

**Files:**
- Create: `ad/GOAD-Mini-Base/` (copy of `ad/GOAD-Mini/`, then edit)
- Modify: `ad/GOAD-Mini-Base/data/config.json`, `data/inventory`, `data/inventory_disable_vagrant`, `providers/*/Vagrantfile`, `README.md`
- Modify: `playbooks.yml` (new `GOAD-Mini-Base` entry)
- Create: `tests/test_base_lab_configs.py`

**Interfaces:**
- Produces: a lab that `Labs` loads, with `capabilities = {"adcs": ["dc01"]}` and `base_settings` with an entry for `dc01` containing every key from Task 8 at its hardened value.

Edits:
- `config.json`: remove every `vulns`, `vulns_vars`, `scripts`, `acls`, `spns`, user `description` that contains a password, any delegation key, and any AS-REP flag. Set every user `password`, `domain_password` and `local_admin_password` to `Aa1234567890!`. Add `capabilities` and `base_settings`.
- `inventory`: empty the `[adcs_customtemplates]` group and set `domain_name=GOAD-Mini-Base`. Remove hosts from `defender_off`, and put every Windows host in `defender_on`.
- `inventory_disable_vagrant`: set `ansible_password=Aa1234567890!` on every host line and `domain_name=GOAD-Mini-Base`.
- Vagrantfiles: replace the hardcoded `GOAD-Mini-` VM name prefix with `{{lab_name}}-`.
- `ansible/adcs.yml` already reads `lab.domains[domain].ca_web_enrollment`, so add `"ca_web_enrollment": false` to the domain in `config.json`.
- `playbooks.yml` entry `GOAD-Mini-Base`: the `GOAD-Mini` list with `ad-acl.yml`, `security.yml` and `vulnerabilities.yml` removed, and `hardening.yml` appended.

- [ ] **Step 1: Write the config lint test**

```python
BASE_LABS = ["GOAD-Mini-Base"]  # Task 10 extends this list

@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_lab_has_no_vulns(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    for h in cfg["hosts"].values():
        assert not h.get("vulns") and not h.get("vulns_vars") and not h.get("scripts")
    for d in cfg["domains"].values():
        assert not d.get("acls")
        for u in d["users"].values():
            assert u["password"] == "Aa1234567890!"
            assert not u.get("spns")
            assert "Aa1234567890" not in u.get("description", "")

@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_lab_passwords_uniform(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    assert all(d["domain_password"] == "Aa1234567890!" for d in cfg["domains"].values())
    assert all(h["local_admin_password"] == "Aa1234567890!" for h in cfg["hosts"].values())
    inv = open(f"ad/{lab}/data/inventory_disable_vagrant").read()
    assert "ansible_password=Aa1234567890!" in inv

@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_settings_cover_all_hosts_and_keys(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    assert set(cfg["base_settings"]) == set(cfg["hosts"])
    for host, settings in cfg["base_settings"].items():
        assert {"net.llmnr", "net.nbtns", "smb.signing", "kerberos.rc4", "firewall.state", "defender.realtime"} <= set(settings)

@pytest.mark.parametrize("lab", BASE_LABS)
def test_playbooks_entry_has_no_vuln_playbooks(lab):
    pb = yaml.safe_load(open("playbooks.yml"))[lab]
    assert "vulnerabilities.yml" not in pb and "security.yml" not in pb and "ad-acl.yml" not in pb
    assert pb[-1] == "hardening.yml"

def test_original_labs_untouched():
    assert subprocess.run(["git", "diff", "--quiet", "main", "--", "ad/GOAD", "ad/GOAD-Light", "ad/GOAD-Mini", "extensions/lx01", "extensions/ws01", "extensions/exchange"]).returncode == 0
```

- [ ] **Step 2: Run, expect failure**

Run: `poetry run pytest tests/test_base_lab_configs.py -v`
Expected: FAIL, `FileNotFoundError: ad/GOAD-Mini-Base/data/config.json`

- [ ] **Step 3: Create the lab**

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 5: Live build and hardening check (VirtualBox)**

Run in `goad`: `set_lab GOAD-Mini-Base`, `set_provider virtualbox`, `install`.
Expected: provisioning ends with `disable_vagrant` and `Lab successfully provisioned`. Then:
- From the host: `nxc smb <ip_range>.10 -u administrator -p 'Aa1234567890!'` shows `(signing:True)`.
- `nxc smb <ip_range>.10 -u vagrant -p vagrant` fails.
- `nxc ldap <ip_range>.10 -u administrator -p 'Aa1234567890!' -M ldap-checker` reports signing and channel binding enforced.
- `curl -s -o /dev/null -w '%{http_code}' http://<ip_range>.10/certsrv/` returns no `401` (web enrollment absent).
- Run `provision_lab` again. It succeeds, which proves the enable_vagrant → run → disable_vagrant loop.

- [ ] **Step 6: Commit**

```bash
git add ad/GOAD-Mini-Base playbooks.yml tests/test_base_lab_configs.py
git commit -m "feat(base): GOAD-Mini-Base hardened lab"
```

### Task 10: `GOAD-Light-Base` and `GOAD-Base` labs

**Files:**
- Create: `ad/GOAD-Light-Base/`, `ad/GOAD-Base/` (copies, then edit as in Task 9)
- Modify: `playbooks.yml` (two new entries, derived from `default` minus `ad-acl.yml`, `security.yml` and `vulnerabilities.yml`, plus `hardening.yml`; `GOAD-Light` uses `default`, so derive both from `default`)
- Modify: `tests/test_base_lab_configs.py` (`BASE_LABS` gains both)

Values:
- `GOAD-Light-Base` capabilities: `{"adcs": ["dc01"], "mssql": ["srv02"], "child_domain": ["dc02"], "member_server": ["srv02"], "laps": ["srv02"]}`
- `GOAD-Base` capabilities: `{"adcs": ["dc01", "srv03"], "mssql": ["srv02", "srv03"], "child_domain": ["dc02"], "forest_trust": ["dc01", "dc03"], "member_server": ["srv02", "srv03"], "laps": ["srv02", "srv03"]}`
- `GOAD-Base` `inventory`: empty `[adcs_customtemplates]` (dc03 drops out). Keep `[adcs]` as `dc01`, `srv03`.
- Remove mssql `linked_servers`, `executeasuser`, `executeaslogin` and every `sysadmins` entry except the domain Administrator from each host's `mssql` block.
- Remove `gmsa` readers except `Domain Admins`.

- [ ] **Step 1: Extend `BASE_LABS` and run, expect failure**

Run: `poetry run pytest tests/test_base_lab_configs.py -v`
Expected: FAIL on the two new labs

- [ ] **Step 2: Create both labs**

- [ ] **Step 3: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 4: Live build `GOAD-Light-Base` (VirtualBox)**

Expected: provisioning succeeds, and the Task 9 Step 5 checks pass against `.10` and `.22`. Then run `nxc mssql <ip_range>.22 -u administrator -p 'Aa1234567890!' -d north.sevenkingdoms.local -q "select name from sys.servers"` and expect only the local server.

- [ ] **Step 5: Commit**

```bash
git add ad/GOAD-Light-Base ad/GOAD-Base playbooks.yml tests/test_base_lab_configs.py
git commit -m "feat(base): GOAD-Light-Base and GOAD-Base hardened labs"
```

### Task 11: Object scenarios `kerberoast` and `asrep-roast`

**Files:**
- Create: `scenarios/kerberoast/{scenario.json,README.md,data/vars.yml,ansible/install.yml,ansible/uninstall.yml}`
- Create: `scenarios/asrep-roast/` (same layout)
- Create: `tests/test_scenario_packages.py`

**Interfaces:**
- Consumes: `scenario_target`, `scenario_name` (from `scenario_run_inventory`), `lab` (from `ansible/data.yml`, with `data_path: "../../../ad/{{domain_name}}/data/"`).
- Every scenario playbook starts by importing `../../../ansible/data.yml`, then plays on `hosts: "{{ scenario_target }}"` with `vars_files: ../data/vars.yml` and `domain: "{{ lab.hosts[scenario_target].domain }}"`.

Values:
- `kerberoast`: `{"description": "Service account with an SPN, roastable", "type": "object", "target": ""}`. vars: `user: svc_kerb`, `spn: "MSSQLSvc/svc-kerb.{{domain}}:1433"`, `password: "Aa1234567890!"`. Install runs `New-ADUser` (if absent), then `Set-ADUser -ServicePrincipalNames @{Add=...}`, then enables the account. Uninstall runs `Remove-ADUser -Confirm:$false` if the user exists. The scenario does not touch encryption types: with `kerberos.rc4` disabled the ticket is AES (`$krb5tgs$18$`, hashcat mode 19700), and the README says so. RC4 roasting becomes a phase-3 `kerberos.rc4` setting scenario.
- `asrep-roast`: `{"description": "User without Kerberos pre-authentication", "type": "object", "target": ""}`. vars: `user: asrep_user`. Install runs `New-ADUser`, then `Set-ADAccountControl -DoesNotRequirePreAuth $true`. Uninstall removes the user.

- [ ] **Step 1: Write the package lint test**

```python
SCENARIOS = sorted(p.name for p in Path("scenarios").iterdir() if (p / "scenario.json").exists())

@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_package_complete(name):
    base = Path("scenarios") / name
    Scenario.from_file(name, str(base) + os.sep)
    for f in ["ansible/install.yml", "ansible/uninstall.yml", "README.md"]:
        assert (base / f).exists(), f

@pytest.mark.parametrize("name", SCENARIOS)
def test_setting_scenario_touches_known_keys(name):
    s = Scenario.from_file(name, f"scenarios/{name}/")
    if s.type == "setting":
        known = {p.stem.replace("_", ".", 1) for p in Path("ansible/roles/base_setting/tasks").glob("*.yml") if p.stem != "main"}
        assert s.touches and set(s.touches) <= known

@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_playbooks_syntax(name):
    for pb in ["install.yml", "uninstall.yml"]:
        r = subprocess.run(["ansible-playbook", "--syntax-check", "-i", "ad/GOAD-Mini-Base/data/inventory", f"scenarios/{name}/ansible/{pb}"], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
```

Note: `known` maps a task file name such as `adcs_web_enrollment.yml` to the key `adcs.web_enrollment` by replacing only the first `_`. Task 8 file names therefore keep the key's first dot as the first underscore (`net_llmnr.yml`, `dc_strong_cert_binding.yml`, `adcs_editf_san.yml`).

- [ ] **Step 2: Run, expect failure** (no packages yet, so collection yields 0 tests; add the two packages' `scenario.json` first, then run)

Run: `poetry run pytest tests/test_scenario_packages.py -v`
Expected: FAIL on missing `ansible/install.yml`

- [ ] **Step 3: Write both packages**

- [ ] **Step 4: Run, expect pass**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 5: Live toggle check (GOAD-Mini-Base)**

`enable_scenario kerberoast`, then from Kali `impacket-GetUserSPNs sevenkingdoms.local/administrator:'Aa1234567890!' -dc-ip <ip_range>.10 -request` returns a `$krb5tgs$18$` hash for `svc_kerb`. `disable_scenario kerberoast`, then the same command returns no entries, and `instance.json` `scenarios` is `[]`. Run enable twice in a row: the second is refused with `already enabled on dc01`. Repeat with `asrep-roast` and `impacket-GetNPUsers`.

- [ ] **Step 6: Commit**

```bash
git add scenarios/kerberoast scenarios/asrep-roast tests/test_scenario_packages.py
git commit -m "feat(scenarios): kerberoast and asrep-roast"
```

### Task 12: Object scenario `esc1`

**Files:**
- Create: `scenarios/esc1/` (layout as Task 11)

Values:
- `scenario.json`: `{"description": "Certificate template where the enrollee supplies the subject, enrollable by Domain Users", "type": "object", "requires": ["adcs"], "target": "adcs"}`
- Install: copy `ansible/roles/adcs_templates/files/ADCSTemplate` and `ansible/roles/adcs_templates/files/ESC1.json` (reference them by relative path, do not duplicate the files), then `New-ADCSTemplate -DisplayName "ESC1" -JSON ... -Identity "<netbios>\Domain Users" -Publish` with the same `runas` vars as `ansible/roles/adcs_templates/tasks/main.yml`. Target is the CA host.
- Uninstall: unpublish (`Remove-CATemplate -Name ESC1 -Force`), then `Remove-ADCSTemplate -DisplayName "ESC1"`.

- [ ] **Step 1: Write the package**

- [ ] **Step 2: Run tests**

Run: `poetry run pytest tests/test_scenario_packages.py -v`
Expected: all pass including `esc1`

- [ ] **Step 3: Live toggle check**

`enable_scenario esc1`, then `certipy find -u administrator@sevenkingdoms.local -p 'Aa1234567890!' -dc-ip <ip_range>.10 -vulnerable -stdout` lists template `ESC1` with `ESC1` in the vulnerabilities. `disable_scenario esc1` removes the template, and the same command lists no vulnerable templates.

- [ ] **Step 4: Commit**

```bash
git add scenarios/esc1
git commit -m "feat(scenarios): esc1"
```

### Task 13: Setting scenarios `esc8` and `llmnr`

**Files:**
- Create: `scenarios/esc8/`, `scenarios/llmnr/` (layout as Task 11)

**Interfaces:**
- Consumes: role `base_setting` (Task 8). Install includes it with the vulnerable value for each key in `touches`. Uninstall includes it with `lab.base_settings[scenario_target][key]`.

Values:
- `esc8`: `{"description": "ADCS web enrollment over HTTP with NTLM, no EPA", "type": "setting", "requires": ["adcs"], "target": "adcs", "touches": ["adcs.web_enrollment"]}`. Install value `true`.
- `llmnr`: `{"description": "LLMNR and NBT-NS enabled on a host", "type": "setting", "target": "member_server", "requires": ["member_server"], "touches": ["net.llmnr", "net.nbtns"]}`. Install values `enabled` / `enabled`. *(Plan's call: target member servers, so GOAD-Mini-Base, which has no member server, does not offer it.)*

- [ ] **Step 1: Write both packages**

- [ ] **Step 2: Run tests**

Run: `poetry run pytest -v`
Expected: all pass

- [ ] **Step 3: Live toggle check**

On GOAD-Mini-Base: `enable_scenario esc8`, then `curl -s -o /dev/null -w '%{http_code}' http://<ip_range>.10/certsrv/` returns `401`, and `certipy find ... -vulnerable -stdout` reports `ESC8`. `disable_scenario esc8` brings back the non-`401` result. Run `provision_lab` with `esc8` enabled: afterwards `/certsrv/` returns `401` again, which proves reapply.
On GOAD-Light-Base: `enable_scenario llmnr`, then from Kali run `responder -I eth1 -A` (analyze mode) and trigger `dir \\nonexistent\x` on srv02. Responder logs an LLMNR query from `.22`. `disable_scenario llmnr`, then the query no longer appears. `list_scenarios all` on GOAD-Mini-Base shows `llmnr` as unavailable with `missing capability member_server`.

- [ ] **Step 4: Commit**

```bash
git add scenarios/esc8 scenarios/llmnr
git commit -m "feat(scenarios): esc8 and llmnr setting scenarios"
```

### Task 14: Docs

**Files:**
- Create: `docs/mkdocs/docs/scenarios.md` (if `docs/mkdocs` exists; otherwise `docs/scenarios.md`)
- Modify: `README.md` (one paragraph and a link under the extensions section)

Content: package layout, `scenario.json` fields table (copy from spec §2), commands, the object vs setting rule, the `base_settings` key table from Task 8, and "how to write a scenario" using `esc8` as the example.

- [ ] **Step 1: Write the docs**
- [ ] **Step 2: Commit**

```bash
git add docs README.md
git commit -m "docs: scenarios"
```
