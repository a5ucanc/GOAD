# Base Tiering Implementation Plan (Plan 1 of the catalogue spec)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `-Base` lab baseline on the Tier 0/1/2 model, apply the hardening-only `security.yml`, drop WebDAV/gMSA provisioning, and make scenario `depends` domain-aware.

**Architecture:** Tiering is data in each Base `config.json` (tier groups, memberships, `local_groups`, `security` lists) plus one new `base_setting` key `host.tier` that applies deny logon rights with `win_user_right`. The engine change is confined to `ScenarioResolver` (new optional `host_domains` map) and its two callers.

**Tech Stack:** Python 3.11 (pytest, venv at `~/.goad/.venv`), Ansible (`ansible.windows`), JSON lab configs.

**Spec:** `docs/superpowers/specs/2026-11-18-base-tiering-and-scenario-catalogue-design.md` — this plan covers Part 1 (sections 1.1–1.7). Part 2 (scenario catalogue) gets its own plans after this one ships.

## Global Constraints

- Run tests with `~/.goad/.venv/bin/pytest -q tests` (system python has no pytest).
- Original labs and extensions stay byte-identical (`test_original_labs_untouched`).
- Passwords are not touched: every account stays `Aa1234567890!`.
- `<domain>\administrator` (built-in, RID 500) is never in any tier group, never in `Protected Users`, never in any deny right.
- Tier group names, exactly: `T0-Admins`, `T1-ServerAdmins`, `T2-WorkstationAdmins` (global groups, `CN=Users,<domain DN>`, in every domain of every Base lab).
- T0 members: sevenkingdoms `cersei.lannister`, `robert.baratheon`; north `eddard.stark`; essos `daenerys.targaryen`. T1 members: north `jeor.mormont`; essos `khal.drogo`. T2: empty. Only domains present in the lab.
- `host.tier` values: `0`, `1`, `2`. DCs `0`, member servers `1`.
- Excluded security roles: `maq0_client`, `maq0_server`, `powershell_restrict`, `ldaps`, `files`, `directory`. ASR rule allowed: only `9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2`.
- Fresh builds only: no removal/cleanup tasks for already-deployed instances.
- Docs: `docs/mkdocs/docs/scenarios.md` is the user doc; written in normal prose.
- Commits only when the user has asked; each task ends with a commit step the executor runs only with that authorization.

## Review Focus

1. **Provisioning lockout:** a deny list containing `Domain Admins`, `Administrators` or `Administrator` would cut Ansible off. Test in Task 2 asserts the computed deny lists only ever hold `<NB>\T{0,1,2}-...` entries.
2. **DC deny rights overridden by GPO:** on DCs, `Default Domain Controllers Policy` wins over local policy for rights it defines. Task 2 live check confirms the deny rights survive `gpupdate /force` on a DC.
3. **Labs with fewer domains:** Mini-Base has one domain; deny lists must only name NetBIOS domains of that lab, or `win_user_right` fails to resolve the principal. Task 2 test covers the per-lab list.
4. **Dependency in another domain:** `rbcd@srv02` with `maq@dc01` must be refused, and `disable maq@dc01` must not cascade to `rbcd@srv02`. Task 1 tests.
5. **Old callers without `host_domains`:** existing tests and any caller constructing `ScenarioResolver` positionally must keep single-domain behaviour. Task 1 test.

---

### Task 1: Domain-aware `depends`

**Files:**
- Modify: `goad/scenario_resolver.py` (constructor, `check_enable` dependency loop, `dependents`)
- Modify: `goad/labs.py:56-68,92` (build `host_domains`, pass it)
- Modify: `goad/scenario_service.py:55` (pass `entry.target`)
- Modify: `docs/mkdocs/docs/scenarios.md` ("Enable rules", "Disable, cascade and dirty")
- Test: `tests/test_scenario_resolver.py`, `tests/test_scenario_service.py`

**Interfaces:**
- Produces: `ScenarioResolver(scenarios, lab_name, capabilities, root_dc, dcs, host_domains: Optional[Dict[str, str]] = None)`; `ScenarioResolver.domain_of(host: str) -> str` (returns `""` when `host_domains` is None or host unknown, so every host shares one domain); `ScenarioResolver.dependents(name: str, enabled: List[EnabledScenario], target: Optional[str] = None) -> List[EnabledScenario]`.
- Refusal string: `requires scenario {dep} in domain {domain}` when `host_domains` is set; unchanged `requires scenario {dep}` when it is None.

- [ ] **Step 1: Write failing tests** in `tests/test_scenario_resolver.py`, with a fixture `domain_resolver` built from the existing `scenarios` fixture plus `make("maq", type="setting", touches=["dc.maq"])`, `make("rbcd", requires=["mssql"], target="mssql", depends=["maq"])`, capabilities `{"adcs": ["dc01", "srv03"], "mssql": ["srv02"]}`, dcs `["dc01", "dc02", "dc03"]`, `host_domains={"dc01": "sevenkingdoms.local", "dc02": "north.sevenkingdoms.local", "srv02": "north.sevenkingdoms.local", "dc03": "essos.local", "srv03": "essos.local"}`:

```python
def test_dependency_in_same_domain_is_met(domain_resolver):
    on = [EnabledScenario("maq", "dc02", "t")]
    assert domain_resolver.check_enable("rbcd", None, on) == "srv02"

def test_dependency_in_other_domain_is_refused(domain_resolver):
    on = [EnabledScenario("maq", "dc01", "t")]
    with pytest.raises(ScenarioRefused) as e:
        domain_resolver.check_enable("rbcd", None, on)
    assert "requires scenario maq in domain north.sevenkingdoms.local" in e.value.reasons

def test_dependents_filtered_by_domain(domain_resolver):
    on = [EnabledScenario("maq", "dc01", "t"), EnabledScenario("maq", "dc02", "t"),
          EnabledScenario("rbcd", "srv02", "t")]
    assert domain_resolver.dependents("maq", on, "dc01") == []
    assert [e.key for e in domain_resolver.dependents("maq", on, "dc02")] == ["rbcd@srv02"]

def test_without_host_domains_any_host_meets_dependency(resolver):
    on = [EnabledScenario("esc8", "srv03", "t")]
    assert resolver.check_enable("relay", None, on) == "dc01"
```

In `tests/test_scenario_service.py` add `test_cascade_only_disables_dependents_in_same_domain`: service with a resolver that has `host_domains`, enabled `maq@dc01`, `maq@dc02`, `rbcd@srv02`; `svc.disable("maq", "dc01")` returns True without `--cascade` and `rbcd@srv02` is still enabled.

- [ ] **Step 2: Run, expect FAIL** — `~/.goad/.venv/bin/pytest -q tests/test_scenario_resolver.py tests/test_scenario_service.py` → failures on the new tests (unexpected keyword `host_domains`).

- [ ] **Step 3: Implement.**
  - Dependency met when some enabled entry has `name == dep` and `domain_of(entry.target) == domain_of(target)`; when `target` is None (target already refused) fall back to name-only.
  - `dependents(name, enabled, target)`: when `target` is given, the root parent's domain is `domain_of(target)` and only entries whose target is in that domain are visited/returned (recursively); `target=None` keeps today's behaviour.
  - `labs.py`: `host_domains = {key: host.get('domain', '') for key, host in hosts.items()}`, stored as `self.host_domains` (reset to `{}` with `dcs`), passed to the resolver.
  - `scenario_service.disable`: `resolver.dependents(name, self.instance.scenarios, entry.target)`.
  - Docs: in "Enable rules" replace the `depends` bullet with "a scenario listed in `depends` is not enabled on a host of the target's domain"; in "Disable, cascade and dirty" say dependents are those in the same domain.

- [ ] **Step 4: Run, expect PASS** — `~/.goad/.venv/bin/pytest -q tests` → all pass.

- [ ] **Step 5: Commit** — `git add goad tests docs/mkdocs && git commit -m "feat(scenarios): domain-aware depends"`

---

### Task 2: `host.tier` base setting

**Files:**
- Create: `ansible/roles/base_setting/tasks/host_tier.yml`
- Create: `ansible/roles/base_setting/vars/tier_rights.yml` (only if the deny-matrix is kept out of the task file; executor's choice)
- Modify: `tests/test_base_lab_configs.py` (`ACCEPTED`)
- Modify: `docs/mkdocs/docs/scenarios.md` (key table + one paragraph on tiers)
- Test: `tests/test_host_tier.py`

**Interfaces:**
- Consumes: role vars `setting_value`, `lab` (lab data), `domain_username`, `domain_password` (same as other keys).
- Produces: key `host.tier` accepting `0`, `1`, `2`.

Deny matrix (`<NB>` = every `lab.domains[*].netbios_name` of the lab):

| tier | `SeDenyInteractiveLogonRight`, `SeDenyRemoteInteractiveLogonRight`, `SeDenyBatchLogonRight`, `SeDenyServiceLogonRight` | `SeDenyNetworkLogonRight` |
|------|------|------|
| 0 | `<NB>\T1-ServerAdmins`, `<NB>\T2-WorkstationAdmins` | none |
| 1 | `<NB>\T0-Admins`, `<NB>\T2-WorkstationAdmins` | `<NB>\T2-WorkstationAdmins` |
| 2 | `<NB>\T0-Admins`, `<NB>\T1-ServerAdmins` | `<NB>\T0-Admins`, `<NB>\T1-ServerAdmins` |

For each of the five rights: `win_user_right` `action: add` with the wanted tier groups, then `action: remove` with the tier groups not wanted (so a tier change converges and non-tier principals are untouched). Skip a call whose user list is empty.

- [ ] **Step 1: Write failing tests** in `tests/test_host_tier.py`. Render the deny lists with a small Jinja harness: load `host_tier.yml`, extract the `set_fact` expressions that compute the per-right lists (the executor names them `tier_deny_interactive` and `tier_deny_network`), render them with `jinja2` for `setting_value` in `0,1,2` and the GOAD-Base / GOAD-Mini-Base `lab` dicts.

```python
@pytest.mark.parametrize("lab", ["GOAD-Base", "GOAD-Light-Base", "GOAD-Mini-Base"])
@pytest.mark.parametrize("tier", ["0", "1", "2"])
def test_deny_lists_only_name_tier_groups_of_lab_domains(lab, tier):
    inter, net = render_tier(lab, tier)
    nbs = {d["netbios_name"].upper() for d in load_lab(lab)["domains"].values()}
    for entry in inter + net:
        nb, group = entry.split("\\")
        assert nb.upper() in nbs
        assert group in {"T0-Admins", "T1-ServerAdmins", "T2-WorkstationAdmins"}

def test_tier0_never_denies_network(): assert render_tier("GOAD-Base", "0")[1] == []
def test_tier1_does_not_deny_t0_network():
    assert not any(e.endswith("\\T0-Admins") for e in render_tier("GOAD-Base", "1")[1])
def test_tier0_denies_t1_interactive_for_every_domain():
    assert {e for e in render_tier("GOAD-Base", "0")[0] if e.endswith("T1-ServerAdmins")} == \
        {"SEVENKINGDOMS\\T1-ServerAdmins", "NORTH\\T1-ServerAdmins", "ESSOS\\T1-ServerAdmins"}
```

Also add `"host.tier": {"0", "1", "2"}` to `ACCEPTED` (test file only; config values come in Task 3).

- [ ] **Step 2: Run, expect FAIL** — `~/.goad/.venv/bin/pytest -q tests/test_host_tier.py` → file not found errors.

- [ ] **Step 3: Implement `host_tier.yml`**: assert value in `['0','1','2']` (same message style as `dc_maq.yml`), two `set_fact` lists per the matrix, then the add/remove `win_user_right` calls looped over the four interactive-class rights and the network right. NetBIOS case as in config (`SEVENKINGDOMS`, `NORTH`, `ESSOS`). Docs: add `| \`host.tier\` | \`0\`, \`1\`, \`2\` |` and a short paragraph with the deny matrix and the note that the built-in Administrator is exempt.

- [ ] **Step 4: Run, expect PASS** — `~/.goad/.venv/bin/pytest -q tests` → all pass.

- [ ] **Step 5: Live check (needs a provisioned GOAD-Base, after Task 3):** on dc01 run `gpupdate /force` then `secedit /export /cfg C:\t.inf /areas USER_RIGHTS` and confirm `SeDenyInteractiveLogonRight` still lists the T1/T2 SIDs. If the Default Domain Controllers Policy overrides it, stop and report: the DC branch then needs to edit that GPO instead (spec deviation for the user to decide).

- [ ] **Step 6: Commit** — `git commit -m "feat(base_setting): host.tier deny logon rights"`

---

### Task 3: Tiered users in Base configs

**Files:**
- Modify: `ad/GOAD-Base/data/config.json`, `ad/GOAD-Light-Base/data/config.json`, `ad/GOAD-Mini-Base/data/config.json`
- Test: `tests/test_base_tiering.py`

**Interfaces:**
- Consumes: `host.tier` (Task 2).
- Produces: tier groups and memberships later scenario plans rely on; capabilities `iis` (GOAD-Base srv02, Light-Base srv02) and `mssql_link` (GOAD-Base srv02).

- [ ] **Step 1: Write failing tests** in `tests/test_base_tiering.py` (parametrized over the three Base labs; T0/T1 expectations from Global Constraints filtered to the lab's domains):

```python
TIERS = {"T0-Admins", "T1-ServerAdmins", "T2-WorkstationAdmins"}
T0 = {"sevenkingdoms.local": {"cersei.lannister", "robert.baratheon"},
      "north.sevenkingdoms.local": {"eddard.stark"}, "essos.local": {"daenerys.targaryen"}}
T1 = {"north.sevenkingdoms.local": {"jeor.mormont"}, "essos.local": {"khal.drogo"}}

def test_tier_groups_in_every_domain(lab): ...        # TIERS <= set(groups["global"]), path CN=Users,<domain DN>
def test_t0_members(lab): ...                          # users with "T0-Admins" == T0[domain]; each also in "Domain Admins" and "Protected Users"
def test_domain_admins_are_exactly_t0(lab): ...        # users with "Domain Admins" == T0[domain]
def test_t1_members(lab): ...                          # users with "T1-ServerAdmins" == T1.get(domain, set())
def test_nobody_else_has_admin_groups(lab): ...        # no other user lists Domain Admins / T0 / T1 / T2
def test_dc_local_groups_empty(lab): ...               # type dc -> local_groups has no "Administrators" and no "Remote Desktop Users" (or is absent)
def test_server_local_admins_are_t1(lab): ...          # type server -> local_groups["Administrators"] == [f"{nb}\\T1-ServerAdmins"]
def test_host_tier_values(lab): ...                    # base_settings[dc]["host.tier"] == 0, server == 1, every host has the key
def test_capabilities(lab): ...                        # iis / mssql_link per spec 1.6 table
```

`nb` is the host domain's `netbios_name` lower-cased as the existing `local_groups` entries are (`north\\...`, `essos\\...`).

- [ ] **Step 2: Run, expect FAIL** — `~/.goad/.venv/bin/pytest -q tests/test_base_tiering.py`.

- [ ] **Step 3: Edit the three configs** to satisfy the tests: add the three tier groups to `groups.global` of every domain; add `"T0-Admins"` and `"Protected Users"` to T0 users' `groups`, `"T1-ServerAdmins"` to T1 users; remove `Domain Admins` from anyone not T0 (none expected — verify); DC `local_groups` → `{}`; server `Administrators` → `["<nb>\\T1-ServerAdmins"]`, keep their `Remote Desktop Users`; add `"host.tier"` to every host's `base_settings` (place it first in each block); add capabilities. Keep the file's 4-space JSON indentation.

- [ ] **Step 4: Run, expect PASS** — `~/.goad/.venv/bin/pytest -q tests` → all pass (including `test_base_lab_has_no_vulns`, `test_base_settings_values_accepted_by_role`).

- [ ] **Step 5: Commit** — `git commit -m "feat(base-labs): tier 0/1/2 users and host.tier"`

---

### Task 4: `security.yml` on Base, WebDAV and gMSA trims

**Files:**
- Modify: Base `config.json` ×3 (`security`, `security_vars` per host)
- Modify: `playbooks.yml` (three Base entries)
- Modify: `ad/GOAD-Base/data/inventory`, `ad/GOAD-Light-Base/data/inventory` (empty `[webdav]`)
- Modify: `tests/test_base_lab_configs.py` (`test_playbooks_entry_has_no_vuln_playbooks`)
- Modify: `docs/mkdocs/docs/scenarios.md` (baseline bullet list: tiers, RunAsPPL, ASR LSASS rule, WebDAV not installed)
- Test: `tests/test_base_tiering.py`

**Interfaces:**
- Consumes: T0 membership from Task 3 (for `account_is_sensitive`).

- [ ] **Step 1: Write failing tests** (in `tests/test_base_tiering.py`):

```python
def test_security_roles(lab):
    # every host: "enable_run_as_ppl" in security
    # server hosts: "asr" in security, security_vars["asr"] has exactly one entry with ruleid 9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2
    # for each domain: its dc (domains[d]["dc"]) has "account_is_sensitive", accounts == T0[domain]
    # no host lists maq0_client, maq0_server, powershell_restrict, ldaps, files, directory

def test_playbook_order(lab):
    pb = yaml.safe_load(open("playbooks.yml"))[lab]
    assert pb[-3:] == ["security.yml", "reboot.yml", "hardening.yml"]
    assert "ad-gmsa.yml" not in pb

def test_webdav_group_empty(lab):
    assert _inventory_group(lab, "webdav") == []   # reuse helper from test_base_lab_configs.py
```

Update `test_playbooks_entry_has_no_vuln_playbooks`: drop the `security.yml` assertion, keep `vulnerabilities.yml` and `ad-acl.yml`.

- [ ] **Step 2: Run, expect FAIL** — `~/.goad/.venv/bin/pytest -q tests`.

- [ ] **Step 3: Implement.** `security_vars.account_is_sensitive` uses the role's dict shape `{"<user>": {"account": "<user>"}}`; `security_vars.asr` = `{"block lsass stealing": {"ruleid": "9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2"}}`. Playbooks: remove `ad-gmsa.yml` from GOAD-Base and GOAD-Light-Base; insert `security.yml`, `reboot.yml` before `hardening.yml` in all three (Mini-Base included). Empty `[webdav]` (keep the header line).

- [ ] **Step 4: Run, expect PASS** — `~/.goad/.venv/bin/pytest -q tests`; also `ansible-playbook --syntax-check` is not needed (no playbook source changed).

- [ ] **Step 5: Commit** — `git commit -m "feat(base-labs): run security.yml, drop webdav and gmsa"`

---

### Task 5: Live verification on GOAD-Base

No code. Needs a fresh GOAD-Base build (fresh builds only).

- [ ] **Step 1:** Build GOAD-Base with the non-interactive `goad.py` flow (see memory: lab host environment). Expected: provisioning completes, vagrant disabled, no failed task.
- [ ] **Step 2:** On dc02, `net localgroup Administrators` lists no `robb.stark`, `catelyn.stark`; on srv02 lists `NORTH\T1-ServerAdmins`.
- [ ] **Step 3:** RDP to srv02 as `north\eddard.stark` → refused (T0 on tier 1). RDP to dc02 as `north\jeor.mormont` → refused. `nxc smb dc02 -u jeor.mormont -p 'Aa1234567890!'` → authenticates (network logon to DC allowed).
- [ ] **Step 4:** `reg query HKLM\SYSTEM\CurrentControlSet\Control\Lsa /v RunAsPPL` = `0x1` on every host; `Get-WindowsFeature WebDAV-Redirector` on srv02 = not installed; `Get-ADDomain | % { Get-ADObject $_ -Properties ms-DS-MachineAccountQuota }` = 0.
- [ ] **Step 5:** `enable_scenario kerberoast`, `disable_scenario kerberoast` still succeed (provisioning account not locked out).
- [ ] **Step 6:** Report results to the user; any failure goes back to the owning task.
