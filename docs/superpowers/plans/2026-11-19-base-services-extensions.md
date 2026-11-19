# Base Services as Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove MSSQL/SSMS/IIS from GOAD-Base and GOAD-Light-Base and deliver them as VM-less `mssql` and `iis` extensions that grant scenario capabilities per instance.

**Architecture:** `extension.json` gains a per-lab `capabilities` map. `Lab.get_scenario_resolver(extensions)` merges the capabilities of the instance's installed extensions into the lab's. The extensions have no `providers/` folder (no VM); their `inventory` template puts existing Base hosts into the `mssql` / `mssql_ssms` / `iis` groups, and their `install.yml` runs the existing `ansible/roles` on those groups.

**Tech Stack:** Python 3 (goad CLI, pytest), Ansible (Windows roles), Jinja inventory templates.

**Spec:** `docs/superpowers/specs/2026-11-19-base-services-extensions-design.md`

## Global Constraints

- Every password is `Aa1234567890!` (sa, `sql_svc`, admins).
- `sql_svc` has no SPN.
- Extensions are compatible with `GOAD-Base` and `GOAD-Light-Base` only.
- GOAD-Base grants: `mssql: [srv02, srv03]`, `mssql_link: [srv02]`, `iis: [srv02]`. GOAD-Light-Base grants: `mssql: [srv02]`, `iis: [srv02]`. No `mssql_link` on Light-Base.
- No changes under `ad/GOAD`, `ad/GOAD-Light`, `ad/GOAD-Mini`, `ad/GOAD-Mini-Base`, `extensions/exchange`, `extensions/lx01`, `extensions/ws01` (`tests/test_base_lab_configs.py:86` enforces part of this).
- Extensions install no vulnerable settings: no impersonation, no linked servers, no low-priv sysadmins.
- Run tests from repo root: `python -m pytest tests -q`.

## Review Focus

- Non-base lab (capabilities `None`) with an extension that declares capabilities: must stay "does not support scenarios", not become base. Test in Task 2.
- Extension installed on a lab not listed in its `capabilities` map: contributes nothing, no crash. Test in Task 1.
- Two extensions granting the same capability key: hosts unioned, no duplicates, lab hosts first. Test in Task 2.
- `remove_extension mssql` while `mssql-sysadmin` and a scenario depending on it are enabled: asks once naming both, disables dependent first, then uninstalls SQL. Tests in Task 3.
- Resolver cache must not return a resolver built for a different extension set (install then list). Test in Task 2.

---

### Task 1: Extension capabilities metadata

**Files:**
- Modify: `goad/extension.py`
- Test: `tests/test_extension.py` (create)

**Interfaces:**
- Produces: `Extension.capabilities_for(lab_name: str) -> Dict[str, List[str]]` — returns a copy of `extension.json["capabilities"][lab_name]`, `{}` when the key, the lab or the file is missing or malformed.

- [ ] **Step 1: Write failing tests** — build extension folders in `tmp_path` and monkeypatch `GoadPath.get_extension_config_file` / `get_extension_providers_path` (pattern: `tests/test_instance_scenarios.py` `build_lab`).
  - `test_capabilities_for_lab`: json `{"capabilities": {"GOAD-Base": {"mssql": ["srv02","srv03"]}}, "compatibility": ["GOAD-Base"], "description": "d", "machines": []}` → `capabilities_for("GOAD-Base") == {"mssql": ["srv02","srv03"]}`.
  - `test_capabilities_for_other_lab_is_empty`: same json → `capabilities_for("GOAD") == {}`.
  - `test_no_capabilities_key`: json without `capabilities` → `{}`.
  - `test_no_providers_folder`: extension folder with no `providers/` loads; `list_providers_name() == []`.
- [ ] **Step 2:** `python -m pytest tests/test_extension.py -q` → FAIL (`AttributeError: capabilities_for`).
- [ ] **Step 3:** In `load_extension_config_file` read `extension_info.get('capabilities') or {}` into `self.capabilities`; add `capabilities_for`. Ignore non-dict values.
- [ ] **Step 4:** Run tests → PASS. Run `python -m pytest tests -q` → PASS.
- [ ] **Step 5:** Commit `feat(extensions): read per-lab capabilities from extension.json`.

### Task 2: Resolver merges extension capabilities

**Files:**
- Modify: `goad/labs.py`, `goad/scenario_service.py`
- Test: `tests/test_instance_scenarios.py`, `tests/test_scenario_service.py`

**Interfaces:**
- Consumes: `Extension.capabilities_for(lab_name)` (Task 1).
- Produces:
  - `Lab.effective_capabilities(extensions: Iterable[str] = ()) -> Optional[Dict[str, List[str]]]` — `None` when the lab has no capabilities; else lab caps, then for each installed extension known to the lab (`self.extensions`) union its `capabilities_for(self.lab_name)` per key, keeping order and dropping duplicates.
  - `Lab.get_scenario_resolver(extensions: Iterable[str] = ()) -> ScenarioResolver` — cached per `tuple(sorted(extensions))`.
  - `ScenarioService` calls `self.lab.get_scenario_resolver(self.instance.extensions)` at all four call sites.

- [ ] **Step 1: Write failing tests** in `tests/test_instance_scenarios.py` (inject a fake extension into `lab.extensions` with a stub `capabilities_for`):
  - `test_extension_capabilities_merged`: lab caps `{"adcs": ["dc01"]}`, ext `{"mssql": ["srv02"]}` → `lab.effective_capabilities(["mssql"]) == {"adcs": ["dc01"], "mssql": ["srv02"]}`.
  - `test_extension_capabilities_union`: lab `{"mssql": ["srv02"]}`, ext `{"mssql": ["srv03","srv02"]}` → `{"mssql": ["srv02","srv03"]}`.
  - `test_non_base_lab_stays_non_base`: lab without capabilities + ext with caps → `effective_capabilities(["mssql"]) is None`.
  - `test_unknown_installed_extension_ignored`: `effective_capabilities(["nope"])` equals lab caps.
  - `test_resolver_cache_per_extension_set`: `get_scenario_resolver([]) is not get_scenario_resolver(["mssql"])`; `get_scenario_resolver(["mssql"]) is get_scenario_resolver(["mssql"])`; the `["mssql"]` resolver's `capabilities` contains `mssql`.
  - Keep `test_scenario_registry` passing (no-arg call).
- [ ] **Step 2:** Update `FakeLab.get_scenario_resolver(self, extensions=())` in `tests/test_scenario_service.py`; add `test_service_passes_instance_extensions`: FakeLab records the `extensions` arg; after `svc.listing(False)` it equals `FakeInstance().extensions`. Give `FakeInstance` an `extensions = ["mssql"]` attribute.
- [ ] **Step 3:** Run both files → FAIL.
- [ ] **Step 4:** Implement in `goad/labs.py` and `goad/scenario_service.py`.
- [ ] **Step 5:** Run `python -m pytest tests -q` → PASS.
- [ ] **Step 6:** Commit `feat(scenarios): merge installed extension capabilities into the resolver`.

### Task 3: Remove extension undoes the install and its dependent scenarios

**Files:**
- Modify: `goad/extension.py`, `goad/extension_service.py`, `goad/scenario_service.py`, `goad.py` (`_extension_service`, `do_provision_extension`, `do_remove_extension`)
- Test: `tests/test_extension_service.py`, `tests/test_scenario_service.py`

**Interfaces:**
- Consumes: `Lab.effective_capabilities(extensions)` and `Lab.get_scenario_resolver(extensions)` (Task 2), `ScenarioResolver.dependents(name, enabled, target)`, `ScenarioResolver.install_order(names)`, `Lab.get_scenario(name)` (`.requires`, `.target`).
- Produces:
  - `Extension.has_uninstall() -> bool` — `<ansible path>/uninstall.yml` exists.
  - `ScenarioService.affected_by_extension_removal(extension: str) -> List[EnabledScenario]` — enabled scenarios whose `target` host is not in `effective_capabilities(remaining)[scenario.target]` or whose `requires` key is missing from it (`remaining` = installed extensions minus `extension`), plus their enabled dependents; ordered for uninstall (dependents first, i.e. reverse `install_order`), no duplicates. DC-targeted scenarios (no `target`) are only affected through `requires`.
  - `ScenarioService.disable_entries(entries: List[EnabledScenario]) -> bool` — uninstalls each in the given order via `_disable_entry`, no revert prompt, stops at the first failure.
  - `ExtensionService(instance, provider, provision, snapshots=None, ask=None, scenarios=None)`; `provision(name, install=True) -> bool`.
  - `ExtensionService.remove(name, yes=False)` order: not installed → `False`; revert offer (unchanged); `affected = scenarios.affected_by_extension_removal(name)` when `scenarios` is set; warn with `extension {name} removal disables scenarios: {keys}`; if not `yes`: no `ask` → error `remove_extension {name} disables scenarios or destroys VMs: use --yes`, else ask `Remove extension {name} and disable scenarios {keys}? (y/N)` (the existing prompt text when `affected` is empty); `scenarios.disable_entries(affected)` → on `False` log `extension {name} kept: disabling scenarios failed` and return `False`; if the extension has an uninstall playbook, `provision(name, install=False)` → on `False` log `extension {name} kept: uninstall failed` and return `False`; then today's VM destroy, `disable_extension`, snapshot forget.
  - `goad.py`: `_extension_service` passes `scenarios=self._scenario_service(ask)` when the lab is base; `do_provision_extension` gains an install flag forwarded to `run_extension(..., install=install)`.

- [ ] **Step 1: Write failing tests** in `tests/test_scenario_service.py` (resolver with `{"mssql": ["srv02","srv03"], "mssql_link": ["srv02"]}` granted by FakeLab only when `"mssql"` is in the extensions passed):
  - `test_affected_by_removal_target`: enabled `mssql-sysadmin@srv02` → `[mssql-sysadmin@srv02]`.
  - `test_affected_by_removal_includes_dependents_first`: enabled `mssql-sysadmin@srv02` and `relay` (depends on it) → keys `["relay@…", "mssql-sysadmin@srv02"]`.
  - `test_affected_ignores_unrelated`: enabled `esc8@dc01` (`adcs`) → `[]`.
  - `test_affected_kept_when_lab_grants`: lab itself grants `mssql: [srv02]` → `[]`.
  - `test_disable_entries_stops_on_failure`: FakeProvisioner fails the first uninstall → returns `False`, second entry still enabled, first marked dirty.
- [ ] **Step 2: Write failing tests** in `tests/test_extension_service.py` (fake `scenarios` object returning a fixed affected list and recording `disable_entries`; fake `provision` recording `(name, install)`):
  - `test_remove_asks_and_disables_scenarios`: affected non-empty, `ask` returns yes → `disable_entries` called with that list, then `provision("mssql", install=False)`, extension removed, returns `True`; the ask text names every key.
  - `test_remove_declined_keeps_everything`: `ask` returns no → `False`, no disable, no provision, extension kept.
  - `test_remove_no_tty_without_yes_refused`: `ask=None`, `yes=False`, affected non-empty → `False`.
  - `test_remove_yes_skips_prompt`: `yes=True` → no ask, disables and uninstalls.
  - `test_remove_scenario_failure_keeps_extension`: `disable_entries` returns `False` → `False`, no uninstall provision, extension kept.
  - `test_remove_uninstall_failure_keeps_extension`: `provision(..., install=False)` returns `False` → `False`, extension kept, VMs not destroyed.
  - `test_remove_without_uninstall_playbook_skips_provision`: VM extension without `uninstall.yml` → no provision call, VMs destroyed (today's behavior).
- [ ] **Step 3:** Run both files → FAIL.
- [ ] **Step 4:** Implement the Interfaces above.
- [ ] **Step 5:** `python -m pytest tests -q` → PASS.
- [ ] **Step 6:** Commit `feat(extensions): remove_extension uninstalls the extension and the scenarios that need it`.

### Task 4: mssql-linked reads its partner from the inventory

**Files:**
- Modify: `scenarios/mssql-linked/ansible/install.yml:39-42`, `scenarios/mssql-linked/ansible/uninstall.yml:31-34`, `scenarios/mssql-linked/README.md`
- Modify: `tests/test_scenario_catalogue.py` (`_non_dc_targets`, `test_setting_baseline_exists_for_every_candidate`)

**Interfaces:**
- Consumes: inventory group `mssql` and host var `mssql_sa_password` (Task 5 inventory).
- Produces: `partner: "{{ groups['mssql'] | difference([scenario_target]) | first }}"`; remote sa password `{{ hostvars[partner].mssql_sa_password }}`. No `lab.capabilities` or `lab.hosts[*].mssql` reads remain in any scenario.

- [ ] **Step 1: Write failing test** in `tests/test_scenario_catalogue.py`: `test_scenarios_do_not_read_lab_mssql_or_capabilities` — for every `scenarios/*/ansible/*.yml`, text contains neither `lab.capabilities` nor `.mssql.`.
- [ ] **Step 2:** Run → FAIL on mssql-linked.
- [ ] **Step 3:** Edit both playbooks; README: "needs the `mssql` extension on GOAD-Base".
- [ ] **Step 4:** Add helper `_caps(lab_name)` in the catalogue test = lab caps merged with every `extensions/*/extension.json` `capabilities[lab_name]` (plain union, no goad import needed); use it in `_non_dc_targets` and `test_setting_baseline_exists_for_every_candidate` so mssql/iis scenarios stay covered once Task 7 strips the labs.
- [ ] **Step 5:** `python -m pytest tests -q` → PASS.
- [ ] **Step 6:** Commit `fix(scenarios): mssql-linked finds its partner through the mssql inventory group`.

### Task 5: `mssql` extension

**Files:**
- Create: `extensions/mssql/extension.json`, `extensions/mssql/inventory`, `extensions/mssql/README.md`, `extensions/mssql/ansible/ansible.cfg` (copy of `extensions/lx01/ansible/ansible.cfg`), `extensions/mssql/ansible/install.yml`, `extensions/mssql/ansible/uninstall.yml`
- No `providers/`, no `data/`.
- Test: `tests/test_service_extensions.py` (create)

**Interfaces:**
- Produces:
  - `extension.json`: `name "mssql"`, `description "Install SQL Server on the Base member servers"`, `machines []`, `compatibility ["GOAD-Base","GOAD-Light-Base"]`, `impact "Installs SQL Server Express on castelblack (and braavos on GOAD-Base); creates sql_svc. Remove does not uninstall it."`, `capabilities` as in Global Constraints, `credentials`: `{"scope": "mssql (castelblack, braavos)", "account": "sa", "password": "Aa1234567890!", "kind": "mssql"}` and `{"scope": "north / essos", "account": "sql_svc", "password": "Aa1234567890!", "kind": "service"}`.
  - `inventory` (Jinja, rendered with `lab_name`): `[mssql]` srv02, plus srv03 when `lab_name == 'GOAD-Base'`; `[mssql_ssms]` srv02; `[mssql:vars]` `mssql_sa_password=Aa1234567890!`; empty `[extensions]`.
  - `install.yml`: imports `../../../ansible/data.yml` (as `extensions/lx01/ansible/install.yml`); play on `mssql` (`serial: 1`) that creates `sql_svc` in the host's domain with `win_domain_user` delegated to `lab.domains[domain].dc` (password `Aa1234567890!`, no SPN), then runs role `mssql` with the vars of `ansible/servers.yml:18-33` except: `SQLSVCACCOUNT: "{{ netbios }}\\sql_svc"`, `SQLSVCPASSWORD: Aa1234567890!`, `sql_sysadmins: ["{{ netbios }}\\Administrator"]`, `sa_password: "{{ mssql_sa_password }}"`, `executeaslogin {}`, `executeasuser {}`, no `mssql_link` role; play on `mssql_ssms` running role `mssql_ssms`.
  - `uninstall.yml`: imports `data.yml`; on `mssql_ssms` uninstall SSMS; on `mssql` (`serial: 1`) uninstall SQL Server (setup.exe `/ACTION=Uninstall /FEATURES=SQLENGINE /INSTANCENAME=<instance the role used>` from the media the role extracted, or the registered uninstaller), remove the `Access for MSSQL (TCP-In)` / `(UDP-In)` firewall rules, remove `sql_svc` from `SeServiceLogonRight`, reboot when required; then delete `sql_svc` with `win_domain_user state: absent` delegated to the domain DC. Idempotent: a second run on a clean host changes nothing and does not fail.
  - `impact` text becomes `... Remove uninstalls SQL Server and SSMS and deletes sql_svc.`

- [ ] **Step 1: Write failing tests** (`tests/test_service_extensions.py`, render the inventory with `jinja2` and parse groups like `_inventory_group` in `tests/test_base_lab_configs.py`):
  - `test_mssql_inventory_matches_capabilities[lab]` for both labs: `[mssql]` hosts == `capabilities[lab]["mssql"]`; `mssql_link` hosts ⊆ `mssql` hosts.
  - `test_mssql_no_link_on_light`: `"mssql_link" not in capabilities["GOAD-Light-Base"]`.
  - `test_mssql_install_has_no_vulns`: `install.yml` text has no `executeaslogin:` with non-empty value, no `mssql_link`, no `setspn`/`spn`.
  - `test_extension_has_no_providers`: `not os.path.exists("extensions/mssql/providers")`.
  - `test_extension_has_uninstall`: `Extension("mssql").has_uninstall()`; `uninstall.yml` text contains `state: absent` and `Uninstall`.
  - `test_extension_loads_in_lab`: `Extension("mssql").capabilities_for("GOAD-Base")["mssql"] == ["srv02","srv03"]`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Create the files.
- [ ] **Step 4:** `python -m pytest tests -q` → PASS. `ansible-playbook --syntax-check -i localhost, extensions/mssql/ansible/install.yml` from `extensions/mssql/ansible` → no syntax error (skip if ansible is not installed on the host; say so in the report).
- [ ] **Step 5:** Commit `feat(extensions): add the VM-less mssql extension`.

### Task 6: `iis` extension

**Files:**
- Create: `extensions/iis/extension.json`, `extensions/iis/inventory`, `extensions/iis/README.md`, `extensions/iis/ansible/ansible.cfg`, `extensions/iis/ansible/install.yml`, `extensions/iis/ansible/uninstall.yml`
- Test: `tests/test_service_extensions.py`

**Interfaces:**
- Produces: `extension.json` with `machines []`, same compatibility, `capabilities {"GOAD-Base": {"iis": ["srv02"]}, "GOAD-Light-Base": {"iis": ["srv02"]}}`; `inventory` `[iis]` srv02, empty `[extensions]`; `install.yml` imports `data.yml` then runs role `iis` on `iis` (as `ansible/servers.yml:8-11`); `uninstall.yml` removes every Windows feature the `iis` role added (`win_feature state: absent`), deletes `C:\inetpub\wwwroot` content the role created, reboots when `reboot_required`. Idempotent.

- [ ] **Step 1:** Parametrize the Task 5 inventory/providers/load/uninstall tests over `["mssql", "iis"]`; add `test_iis_inventory_matches_capabilities`.
- [ ] **Step 2:** Run → FAIL for iis.
- [ ] **Step 3:** Create the files.
- [ ] **Step 4:** `python -m pytest tests -q` → PASS.
- [ ] **Step 5:** Commit `feat(extensions): add the VM-less iis extension`.

### Task 7: Strip services from the Base labs

**Files:**
- Modify: `ad/GOAD-Base/data/config.json`, `ad/GOAD-Base/data/inventory`, `ad/GOAD-Base/README.md`, `ad/GOAD-Light-Base/data/config.json`, `ad/GOAD-Light-Base/data/inventory`, `ad/GOAD-Light-Base/README.md`
- Modify: `tests/test_base_tiering.py:14-18,90-94`
- Test: `tests/test_base_lab_configs.py`

**Interfaces:**
- Produces: Base configs with no `mssql` host blocks, no `sql_svc` users, no `iis`/`mssql`/`mssql_link` capability keys; inventories with empty `[iis]`, `[mssql]`, `[mssql_ssms]` groups (keep the group headers and comments).

- [ ] **Step 1: Write failing test** in `tests/test_base_lab_configs.py`: `test_base_lab_has_no_services[lab]` — no host has `mssql`; no domain user named `sql_svc`; `capabilities` has none of `iis`, `mssql`, `mssql_link`; inventory groups `iis`, `mssql`, `mssql_ssms`, `mssql_link` are empty.
- [ ] **Step 2:** Run → FAIL for GOAD-Base and GOAD-Light-Base.
- [ ] **Step 3:** Edit configs and inventories. In `test_base_tiering.py` set `CAPABILITIES` to `{}` for every lab (the test then asserts the keys are absent).
- [ ] **Step 4:** READMEs: replace the MSSQL/IIS wording with "No services: MSSQL and IIS come from the `mssql` and `iis` extensions (`install_extension mssql`)."
- [ ] **Step 5:** `python -m pytest tests -q` → PASS.
- [ ] **Step 6:** Commit `feat(base): move MSSQL and IIS out of the Base labs`.

### Task 8: Live check on a VMware GOAD-Base instance (manual, needs the user's lab)

- [ ] On a fresh GOAD-Base instance: `install_extension mssql`, then `list_scenarios` shows `mssql-sysadmin` and `mssql-linked` available; `enable_scenario mssql-linked` succeeds and `use_link BRAAVOS` works per `scenarios/mssql-linked/README.md`.
- [ ] Before the install, `enable_scenario mssql-sysadmin` is refused with `missing capability mssql`.
- [ ] With `mssql-sysadmin` and `mssql-linked` enabled, `remove_extension mssql` lists both and asks; answering yes disables both, uninstalls SQL from castelblack and braavos (service gone, port 1433 closed), deletes `sql_svc`, and `list_scenarios` shows them unavailable again.
- [ ] `install_extension mssql` after the removal works again.
- [ ] Same remove/reinstall cycle for `iis` with `iis-upload` enabled.
- [ ] Report results; no commit.
