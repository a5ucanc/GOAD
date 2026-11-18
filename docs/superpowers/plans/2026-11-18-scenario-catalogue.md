# Scenario Catalogue Implementation Plan (Plan 2 of the catalogue spec)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add every scenario package listed in spec Part 2 (settings, ADCS, delegation, ACL, MSSQL, IIS) to `scenarios/`, each with an uninstall that returns the lab to the Base baseline, and prove both directions live.

**Architecture:** One folder per scenario following `docs/mkdocs/docs/scenarios.md`. Setting scenarios reuse the esc8/llmnr playbook shape and `base_setting`; five new `base_setting` keys come first. ACL and delegation scenarios share one role, `ansible/roles/scenario_acl`. A catalogue test pins each package's metadata and its uninstall references; the existing package tests check syntax and role paths. A live snapshot-diff procedure proves disable leaves no residue.

**Tech Stack:** Ansible (`ansible.windows`), PowerShell AD/ADCS modules, `ADCSTemplate` module (`ansible/roles/adcs_templates/files/ADCSTemplate`), PSPKI (esc7), SqlCmd, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-base-tiering-and-scenario-catalogue-design.md` — Part 2 (2.1–2.7), 1.6 capabilities, anti-goal "a disabled scenario leaves residue". Plan 1 (`2026-11-18-base-tiering.md`) is done.

## Global Constraints

- Tests: `export PATH=$HOME/.goad/.venv/bin:$PATH; pytest -q tests`.
- Package layout: `scenario.json`, `README.md` (what it does, attack, verification, what disable removes, what disable does **not** clean), `data/vars.yml`, `ansible/install.yml`, `ansible/uninstall.yml`.
- Playbook header as `scenarios/esc8`: `import_playbook: "../../../ansible/data.yml"`, `hosts: scenario_target`, vars `domain: "{{ lab.hosts[scenario_target].domain }}"`, `domain_username: "{{ domain }}\\administrator"`, `domain_password: "{{ lab.domains[domain].domain_password }}"`, `netbios: "{{ lab.domains[domain].netbios_name }}"`, `dc: "{{ lab.domains[domain].dc }}"`.
- Roles by path: `"{{ playbook_dir }}/../../../ansible/roles/<role>"`.
- **AD location rule:** every AD read/write (AD cmdlets, `AD:` drive, `[ADSI]`, `scenario_acl`) runs on `{{ dc }}`. When `scenario_target != dc` the task carries `delegate_to: "{{ dc }}"` (for `include_role`: `apply: { delegate_to: "{{ dc }}" }`). Host-local changes (local groups, files, SQL, CA config) run on the target.
- **Write pattern:** check, then write. Every create/add is skipped when present; every delete/remove is skipped when absent. PowerShell blocks set `$ErrorActionPreference = 'Stop'` and `$Ansible.Changed` correctly.
- **Names:** scenario-created AD objects `scn-...` (≤ 20 chars), users/groups in `CN=Users,<dn>`, password `Aa1234567890!`. Lab/built-in objects are never deleted; uninstall removes only what the scenario added to them.
- **Disable contract** (every package):
  1. Uninstall restores exactly the Base state of everything the scenario owns, in reverse dependency order (memberships and ACEs before the principals they reference).
  2. Uninstall passes on a lab where install never ran or stopped half-way, and when run twice.
  3. Install passes when run twice (re-provision re-applies).
  4. **Attack leftovers that are cheap to clean are cleaned:** certificates issued from a scenario template are revoked (`certutil -view -restrict "CertificateTemplate=<template OID>" -out SerialNumber csv`, `certutil -revoke <serial>`, `certutil -crl`); computers with `mS-DS-CreatorSID` set (created through MAQ) are deleted by `maq` and `rbcd` uninstall (Base has none); `msDS-AllowedToActOnBehalfOfOtherIdentity` and `msDS-KeyCredentialLink` are cleared on lab objects a scenario granted write on (the Base value is empty); `xp_cmdshell` and `show advanced options` reset to `0` by MSSQL uninstalls. Leftovers that are not cleaned (GPO settings tattooed on hosts, passwords the attacker changed on scenario users that are deleted anyway) are listed in the README.
  5. **Accepted tooling residue:** `ADCSTemplate` module, `C:\setup\*.json`, PSPKI and NuGet provider stay installed (same as `esc1`).
- Setting scenarios: install sets `vulnerable_value`; uninstall sets `lab.base_settings[scenario_target][key]`; keys listed in `touches`.
- `type: object` unless stated; `target` empty = DC.
- Out of scope: bots, secrets, passwords, `tier-violation`, gMSA/LAPS read, NHA/DRACARYS/SCCM/Exchange.
- Commit at the end of each task on `feat/base-tiering`, messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Residue after disable:** covered by the snapshot diff of Tasks 10–11; unit test `test_uninstall_references_every_scn_name` catches forgotten objects early.
2. **Uninstall after partial install / twice:** live in Tasks 10–11 (direct `uninstall.yml` runs on a clean lab and twice).
3. **Wrong domain / missing AD module:** AD location rule, `test_ad_tasks_delegate_to_dc` (Task 7).
4. **Baseline key missing on a candidate host:** `test_setting_baseline_exists_for_every_candidate` (Task 3).
5. **SDProp on `acl-adminsdholder`:** uninstall triggers `runProtectAdminGroupsTask`; Task 10 polls protected-object DACLs up to 60 min.

---

### Task 1: Engine — failed cleanup is recorded dirty

**Files:** Modify `goad/scenario_service.py` (`enable`); Test `tests/test_scenario_service.py`.

- [ ] **Step 1: Failing test** `test_failed_install_and_failed_cleanup_marks_dirty`: `prov.fail_on = {("esc8", True), ("esc8", False)}`; `svc.enable("esc8", None)` returns False; `svc.instance.scenarios` holds `esc8@dc01` with `status == "dirty"`. Keep `test_failed_install_cleans_up_and_records_nothing` (cleanup succeeds → nothing recorded).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** In `enable`, when the cleanup `_run(name, target, False)` fails: `self.instance.add_scenario(name, target)`, `self.instance.mark_scenario_dirty(name, target)`, `Log.error(f'cleanup of {name}@{target} failed, marked dirty: run disable_scenario {name} {target}')`. Docs "Disable, cascade and dirty": add the sentence.
- [ ] **Step 4:** `pytest -q tests` → PASS. **Step 5:** commit `fix(scenarios): record a failed cleanup as dirty`.

---

### Task 2: New `base_setting` keys

**Files:** Create `ansible/roles/base_setting/tasks/dc_cert_mapping.yml`, `smb_v1.yml`, `winrm_credssp.yml`, `trust_sid_history.yml`, `net_webclient.yml`; Modify the three Base `config.json`, `tests/test_base_lab_configs.py` (`ACCEPTED`), docs key table.

| Key | Values (baseline first) | Baseline on | Read state / apply |
|-----|--------|-------------|--------|
| `dc.cert_mapping` | `absent`, `0x4` | every DC | `HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\Schannel` `CertificateMappingMethods`. `absent` deletes the value (live dc01: value absent, Windows default `0x18`); `0x4` writes the dword. No reboot (Schannel reads it per handshake; Task 10 confirms with `certipy auth -ldap-shell`). |
| `smb.v1` | `disabled`, `enabled` | every host | `Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol`; `Enable-/Disable-WindowsOptionalFeature -NoRestart`; state `EnablePending`/`DisablePending` or `RestartNeeded` → `win_reboot`, then re-check. |
| `winrm.credssp` | `disabled`, `server`, `client` | member servers | read `WSMan:\localhost\Service\Auth\CredSSP` and `WSMan:\localhost\Client\Auth\CredSSP`; change only roles whose state differs: `Disable-WSManCredSSP -Role Server/Client`, `Enable-WSManCredSSP -Role Server -Force` or `-Role Client -DelegateComputer * -Force`. |
| `trust.sid_history` | `disabled`, `enabled` | hosts in `forest_trust` | for the partner `lab.domains[domain].trust` (skip when empty): read `trustAttributes` of `CN=<partner>,CN=System,<dn>`, bit `0x40` = enabled; when different run `netdom trust <domain> /d:<partner> /enablesidhistory:yes|no /ud:<partner NB>\administrator /pd:<partner domain_password>`. On dc01 this lets sevenkingdoms accept SID history from essos users (README states direction). |
| `net.webclient` | `absent`, `present` | member servers | `Get-WindowsFeature WebDAV-Redirector`; install/uninstall with `win_feature`, `win_reboot` when `reboot_required`; `present` also sets service `WebClient` auto + started. |

- [ ] **Step 1: Failing test** — `ACCEPTED` gets the five keys; `test_new_keys_baseline`: every DC `dc.cert_mapping == "absent"`, every host `smb.v1 == "disabled"`, every `member_server` host `winrm.credssp == "disabled"` and `net.webclient == "absent"`, every `forest_trust` host `trust.sid_history == "disabled"`.
- [ ] **Step 2:** run → FAIL. **Step 3:** task files (assert values like `dc_maq.yml`), baselines (json `indent=4` round-trip), docs rows. **Step 4:** `pytest -q tests` → PASS; `ansible-playbook --syntax-check -i ad/GOAD-Base/data/inventory ansible/hardening.yml` → ok. **Step 5:** commit `feat(base_setting): cert mapping, smbv1, credssp, sid history, webclient keys`.

---

### Task 3: Setting scenarios (spec 2.1 + 2.2)

**Files:** 18 packages; Create `tests/test_scenario_catalogue.py`.

**Interfaces:** Produces `CATALOGUE` (dict name → `type`, `target`, `requires`, `depends`, `touches`) that Tasks 4–8 extend; scenario names `maq` (rbcd), `esc10-case1` (esc9).

| Name | key → vulnerable_value | target | requires |
|------|------------------------|--------|----------|
| `smb-signing-off` | `smb.signing: optional` | `member_server` | `[member_server]` |
| `ntlm-downgrade` | `ntlm.lmcompat: 2` | `""` | — |
| `ldap-signing-off` | `ldap.signing: none` | `""` | — |
| `ldap-cbt-off` | `ldap.channel_binding: never` | `""` | — |
| `printerbug` | `dc.spooler: enabled` | `""` | — |
| `esc10-case1` | `dc.strong_cert_binding: 0` | `""` | `[adcs]` |
| `esc10-case2` | `dc.cert_mapping: "0x4"` | `""` | `[adcs]` |
| `esc6` | `adcs.editf_san: on` | `adcs` | `[adcs]` |
| `esc11` | `adcs.enforce_encrypt: off` | `adcs` | `[adcs]` |
| `rc4` | `kerberos.rc4: enabled` | `""` | — |
| `mdns` | `net.mdns: enabled` | `member_server` | `[member_server]` |
| `defender-off` | `defender.realtime: off` | `member_server` | `[member_server]` |
| `firewall-off` | `firewall.state: off` | `member_server` | `[member_server]` |
| `maq` | `dc.maq: 10` | `""` | — |
| `smbv1` | `smb.v1: enabled` | `member_server` | `[member_server]` |
| `credssp` | `winrm.credssp: server` | `member_server` | `[member_server]` |
| `sid-history` | `trust.sid_history: enabled` | `forest_trust` | `[forest_trust]` |
| `webdav` | `net.webclient: present` | `member_server` | `[member_server]` |

Disable: uninstall applies the baseline value (esc8 shape). Extra: `maq` uninstall also deletes every computer in the target's domain with `mS-DS-CreatorSID` set (after restoring the quota). `esc6` README states that certificates issued with a SAN while the flag was on stay valid (they cannot be told apart from normal issuance); revoke them by hand with `certutil -revoke`.

- [ ] **Step 1: Failing tests** in `tests/test_scenario_catalogue.py`:
  - `test_catalogue_package(name)`: `Scenario.from_file` fields equal `CATALOGUE[name]` (missing lists = `[]`).
  - `test_setting_vars(name)` (setting rows): `touched_settings == [{"key": k, "vulnerable_value": v}]`.
  - `test_setting_uninstall_restores_baseline(name)` (every setting scenario): `uninstall.yml` passes `setting_value: "{{ lab.base_settings[scenario_target][scenario_setting.key] }}"`.
  - `test_setting_baseline_exists_for_every_candidate`: for each Base lab and setting scenario whose `requires` the lab meets, for each candidate host (`capabilities[target]`, or every `type == "dc"` host when target empty), every touched key is in `base_settings[host]`.
  - `test_scn_names_fit_sam(name)`: every `scn-*` string in `data/vars.yml` ≤ 20 chars.
  - `test_uninstall_references_every_scn_name(name)` (all scenarios): every `scn-*` string and every `template`/`templates` value in `data/vars.yml` is referenced in `uninstall.yml` (literally or through the same vars key).
- [ ] **Step 2:** run → FAIL. **Step 3:** packages (play names `Install <name> scenario` / `Uninstall <name> scenario`), READMEs (e.g. `printerbug`: `coercer coerce -l <attacker> -t <dc> --filter-method-name RpcRemoteFindFirstPrinterChangeNotificationEx`, verify `Get-Service Spooler`). **Step 4:** `pytest -q tests` → PASS. **Step 5:** commit `feat(scenarios): setting scenarios`.

---

### Task 4: ADCS object scenarios (spec 2.3)

**Files:** `scenarios/esc2`, `esc3`, `esc4`, `esc7`, `esc9`, `esc13`, `esc15`; extend `CATALOGUE`.

All `target: adcs`, `requires: [adcs]`. Template work as `scenarios/esc1` (module copy, `runas` become). AD objects (users, groups, ACEs, OID objects) follow the AD location rule (srv03 is the essos CA and not a DC). Before removing a template, revoke its issued certificates (Disable contract 4), then `Remove-CATemplate` if published, then `Remove-ADCSTemplate` if present.

| Name | depends | Install | Uninstall (in order) |
|------|---------|---------|-----------|
| `esc2` | — | template `ESC2` from `ESC2.json`, enroll `<NB>\Domain Users`, publish | revoke, unpublish, remove |
| `esc3` | — | `ESC3-CRA` and `ESC3` from their JSON, both enroll `<NB>\Domain Users`, publish | for each template independently: revoke, unpublish, remove |
| `esc4` | — | template `ESC4` (enroll Domain Users); user `scn-esc4-user`; `GenericAll` for it on the template object (`scenario_acl`) | revoke, unpublish, remove template (its DACL goes with it), remove user |
| `esc7` | — | user `scn-esc7-user`; PSPKI if missing; `ManageCa` for the user's SID on the CA; restart `certsvc` | if PSPKI present and user exists: remove CA ACEs for the user's SID (`Get-CertificationAuthorityAcl` / `Remove-CertificationAuthorityAcl`), `Set-CertificationAuthorityAcl -RestartCA`; then revoke certs issued to `<NB>\scn-esc7-user` and any certs issued while it held ManageCa from templates it enabled (README: officer actions are not tracked); remove user |
| `esc9` | `[esc10-case1]` | template `ESC9`, enroll Domain Users; users `scn-esc9-attacker`, `scn-esc9-victim`; `GenericWrite` attacker → victim | revoke, unpublish, remove template; remove users |
| `esc13` | — | template `ESC13`, enroll Domain Users; universal group `scn-esc13-group` member of `BUILTIN\Administrators`; **inline idempotent PowerShell** (not `esc13.ps1`): reuse the `msPKI-Enterprise-Oid` with `DisplayName=IssuancePolicyESC13` if present, else create one (OID under the forest OID, as `esc13.ps1`); set the template `msPKI-Certificate-Policy` to it; set its `msDS-OIDToGroupLink` to the group DN | revoke, unpublish, remove template; delete **every** OID object with `DisplayName=IssuancePolicyESC13`; remove group membership, group |
| `esc15` | — | `Set-ADCSTemplateACL -DisplayName "Web Server" -Type Allow -Identity "<NB>\Domain Users" -Enroll` (adds two ACEs: `GenericRead` and `ExtendedRight` `0e10c968-78fb-11d2-90d4-00c04f79dc55`) | `Get-Acl "AD:CN=WebServer,CN=Certificate Templates,CN=Public Key Services,CN=Services,<configNC>"`, remove the explicit (`IsInherited -eq $false`) Allow ACEs for `<NB>\Domain Users` with exactly those rights/GUID, `Set-Acl`. README: Web Server certificates issued during the scenario stay valid (lab template, not revoked) |

`esc9`: README says `esc10-case1` must be enabled on the DC of the CA's domain. Disable `esc10-case1` refuses while `esc9` is enabled there; `--cascade` removes `esc9` first.

- [ ] **Step 1:** extend `CATALOGUE`; run → FAIL. **Step 2:** packages; READMEs `certipy req -u ... -ca <NB>-CA -template <T>` and `certutil -catemplates`. **Step 3:** `pytest -q tests` → PASS. **Step 4:** commit `feat(scenarios): adcs object scenarios`.

---

### Task 5: `scenario_acl` role + ACL scenarios (spec 2.5)

**Files:** Create `ansible/roles/scenario_acl/tasks/add.yml`, `remove.yml`; 16 packages; extend `CATALOGUE`.

**Interfaces (`scenario_acl`):** `include_role` with `tasks_from: add|remove`, vars `acl_principal` (sAMAccountName, `<NB>\name` for another domain, or `NT AUTHORITY\ANONYMOUS LOGON`), `acl_target_dn`, `acl_right` (`GenericAll`, `GenericWrite`, `WriteDacl`, `WriteOwner`, `WriteProperty`, `ReadProperty`, `GenericExecute`, `Ext-User-Force-Change-Password`, `Ext-Self-Self-Membership`, `Ext-Write-Self-Membership`, `Ext-Validated-SPN` = `Self` + `f3a64788-5306-11d1-a9c5-0000f80367c1`), `acl_inheritance` (`None`|`All`). Runs on `{{ dc }}` (caller adds `apply: delegate_to` when needed), `runas` become.
- `add`: resolve principal SID; skip if an explicit ACE with identical identity/rights/type/ObjectType/InheritanceType exists; else add.
- `remove`: if the principal or target does not resolve → no change, success. Remove only explicit (`IsInherited -eq $false`) ACEs matching identity, rights, type `Allow`, ObjectType and InheritanceType exactly.

| Name | Install | Uninstall (in order) |
|------|---------|---------|
| `acl-forcechangepassword` | users `scn-acl-fcp-attacker`, `scn-acl-fcp-victim`; ACE `Ext-User-Force-Change-Password`/None attacker → victim | remove users (ACE goes with victim) |
| `acl-genericwrite-user` | `scn-acl-gwu-attacker` → `scn-acl-gwu-victim`, `GenericWrite`/None | remove users |
| `acl-writedacl-user` | `scn-acl-wdu-attacker` → `scn-acl-wdu-victim`, `WriteDacl`/None | remove users |
| `acl-self-membership` | user `scn-acl-sm-attacker`, group `scn-acl-sm-group`, `Ext-Self-Self-Membership`/None | remove group, user |
| `acl-addmember` | user `scn-acl-add-attacker`, group `scn-acl-add-group`, `Ext-Write-Self-Membership`/All | remove group, user |
| `acl-writeowner` | user `scn-acl-wo-attacker`, group `scn-acl-wo-group`, `WriteOwner`/None | remove group, user |
| `acl-genericall-user` | `scn-acl-gau-attacker` → `scn-acl-gau-victim`, `GenericAll`/None | remove users |
| `acl-genericall-computer` | user `scn-acl-gac-attacker`, `GenericAll`/None on the DC computer object | `scenario_acl remove`; clear `msDS-KeyCredentialLink` and `msDS-AllowedToActOnBehalfOfOtherIdentity` on the DC object; delete computers with `mS-DS-CreatorSID` = attacker SID; remove user |
| `acl-genericall-group` (target `member_server`, requires `[member_server]`) | user `scn-acl-gag-attacker`; domain-local group `scn-acl-gag-group` (on DC); group added to the target's local `Administrators` (`win_group_membership`, on target); ACE `GenericAll`/None attacker → group | on target: if the group still resolves, remove it from local `Administrators`; then remove group, user (on DC). README: if the group was deleted first, the orphan SID is removed with `Remove-LocalGroupMember -Member <SID>` — uninstall does this by SID read from the DC before deleting the group |
| `acl-adminsdholder` | user `scn-acl-sdh-attacker`; `GenericAll`/None on `CN=AdminSDHolder,CN=System,<dn>` | `scenario_acl remove`; `([ADSI]"LDAP://{{ dc fqdn }}/RootDSE").Put("runProtectAdminGroupsTask",1); .SetInfo()`; remove user (README: SDProp copies the ACE to protected objects; it is gone from them after the next SDProp run, the uninstall triggers one) |
| `acl-writedacl-ou` | OU `OU=scn-acl-wdo,<dn>` created with `-ProtectedFromAccidentalDeletion $false`; user `scn-acl-wdo-victim` inside; user `scn-acl-wdo-attacker` in `CN=Users`; `WriteDacl`/None attacker → OU | if OU exists: `Set-ADObject -ProtectedFromAccidentalDeletion $false`, `Remove-ADObject -Recursive -Confirm:$false`; remove attacker |
| `acl-writeproperty` | `scn-acl-wp-attacker` → `scn-acl-wp-victim`, `WriteProperty`/All | remove users |
| `anonymous-rpc` | `NT AUTHORITY\ANONYMOUS LOGON` on domain root: `ReadProperty`/All and `GenericExecute`/All (GOAD north `anonymous_rpc`; anonymous RPC/SAMR enumeration, not anonymous LDAP search) | `scenario_acl remove` both (explicit exact match only; Task 10 asserts no such ACE exists in Base before install) |
| `gpo-abuse` | user `scn-gpo-attacker`; GPO `scn-gpo-abuse` if absent; link to domain root if not linked; `Set-GPPermission -TargetType User -PermissionLevel GpoEditDeleteModifySecurity` | if GPO exists: `Remove-GPLink` if linked, `Remove-GPO`; remove user. README: settings the attacker pushed stay tattooed on hosts that applied them |
| `foreign-group-acl` (target `forest_trust`, requires `[forest_trust]`) | partner = `lab.domains[domain].trust`; user `scn-foreign-user` in the partner domain (`-Server <partner dc fqdn> -Credential <partner NB>\administrator`/partner `domain_password`); domain-local group `scn-foreign-group` in the target domain with that user as member (creates an FSP); `GenericAll`/None group → target DC computer object | read partner user SID (if present); `scenario_acl remove`; remove group; delete `CN=<SID>,CN=ForeignSecurityPrincipals,<dn>` if present; remove partner user (`-Server`/`-Credential`) |
| `local-admin` (target `member_server`, requires `[member_server]`) | user `scn-local-admin` (on DC); member of target's local `Administrators` | on target: if user resolves, remove from `Administrators` (by SID); then remove user (on DC) |

All other targets `""`.

- [ ] **Step 1:** extend `CATALOGUE`; `test_scenario_acl_role_parses` (both task files load, define the five vars in an assert). Run → FAIL. **Step 2:** role, packages; READMEs with `bloodyAD`/`dacledit.py`/`owneredit.py`/`pygpoabuse`/`rpcclient -U ""`. **Step 3:** `pytest -q tests` → PASS. **Step 4:** commit `feat(scenarios): acl scenarios`.

---

### Task 6: Delegation scenarios (spec 2.4)

**Files:** `scenarios/constrained-deleg-any`, `constrained-deleg-kerb`, `unconstrained-computer`, `unconstrained-user`, `rbcd`, `writespn`; extend `CATALOGUE`. Consumes `scenario_acl` (Task 5).

| Name | target / requires / depends | Install | Uninstall (in order) |
|------|-----------------------------|---------|-----------|
| `constrained-deleg-any` | `""` | user `scn-cdany-svc`, SPN `HTTP/scn-cdany.<domain>`, `TrustedToAuthForDelegation`, `msDS-AllowedToDelegateTo` `CIFS/<dc fqdn>`, `CIFS/<dc hostname>` | remove user |
| `constrained-deleg-kerb` | `member_server` / `[member_server]` | on `<host>$`: add each of `HTTP/<dc fqdn>`, `HTTP/<dc hostname>` to `msDS-AllowedToDelegateTo` only if absent | remove each value only if present (Base value is empty) |
| `unconstrained-computer` | `member_server` / `[member_server]` | `TrustedForDelegation $true` on `<host>$` if not set | set `$false` if set |
| `unconstrained-user` | `""` | user `scn-unconst-svc`, SPN `HTTP/scn-unconst.<domain>`, `TrustedForDelegation` | remove user |
| `rbcd` | `member_server` / `[member_server]` / `[maq]` | user `scn-rbcd-attacker`; `GenericWrite`/None attacker → `<host>$` | `scenario_acl remove`; clear `msDS-AllowedToActOnBehalfOfOtherIdentity` and `msDS-KeyCredentialLink` on `<host>$`; delete computers with `mS-DS-CreatorSID` = attacker SID; remove user |
| `writespn` | `""` | users `scn-wspn-attacker`, `scn-wspn-victim`; `Ext-Validated-SPN`/None attacker → victim | remove users |

- [ ] **Step 1:** extend `CATALOGUE`; run → FAIL. **Step 2:** packages; READMEs `findDelegation.py`, `getST.py -spn ... -impersonate Administrator`, `addcomputer.py` + `rbcd.py`. **Step 3:** `pytest -q tests` → PASS. **Step 4:** commit `feat(scenarios): delegation scenarios`.

---

### Task 7: MSSQL + IIS scenarios (spec 2.6, 2.7) and the AD location test

**Files:** `scenarios/mssql-impersonate-login`, `mssql-impersonate-user`, `mssql-sysadmin`, `mssql-linked`, `iis-upload`; extend `CATALOGUE`; add `test_ad_tasks_delegate_to_dc`.

SQL: `SqlCmd -E -b -Q "<T-SQL>"` on the target (the connection account is sysadmin on Base; `-b` makes T-SQL errors fail the task). Deviation from spec 2.6 ("use the mssql vulns role's SQL task"): that task has no `-b` and no guards. Every statement guarded:
- create login: `IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name=N'<NB>\x')`
- drop login: kill sessions `SELECT session_id FROM sys.dm_exec_sessions WHERE login_name=N'<NB>\x'` → `KILL`, then `IF EXISTS ... DROP LOGIN`
- db user: `USE msdb; IF EXISTS (SELECT 1 FROM sys.database_principals WHERE name=N'<NB>\x') DROP USER [...]`
- linked server: `IF EXISTS (SELECT 1 FROM sys.servers WHERE name=N'<NAME>') EXEC sp_dropserver N'<NAME>', 'droplogins'`
- every MSSQL uninstall ends with `EXEC sp_configure 'xp_cmdshell',0; RECONFIGURE; EXEC sp_configure 'show advanced options',0; RECONFIGURE;` (Base values).
AD users for MSSQL scenarios follow the AD location rule (target is srv02/srv03).

| Name | target / requires | Install | Uninstall (in order) |
|------|-------------------|---------|-----------|
| `mssql-impersonate-login` | `mssql` / `[mssql]` | AD user `scn-sql-imp`; login; `GRANT IMPERSONATE ON LOGIN::[sa] TO [<NB>\scn-sql-imp]` | drop login (revokes grant), reset config, remove AD user |
| `mssql-impersonate-user` | `mssql` / `[mssql]` | AD user `scn-sql-dbo`; login; msdb user; `GRANT IMPERSONATE ON USER::[dbo]` in msdb | drop msdb user, drop login, reset config, remove AD user |
| `mssql-sysadmin` | `mssql` / `[mssql]` | AD user `scn-sql-admin`; login; `ALTER SERVER ROLE sysadmin ADD MEMBER` | for every database owned by the login `ALTER AUTHORIZATION ON DATABASE::<db> TO sa`; drop login; reset config; remove AD user |
| `mssql-linked` | `mssql_link` / `[mssql_link]` | partner = the other host in `capabilities.mssql`, link name = `lab.hosts[partner].hostname | upper`; AD user `scn-sql-link`; login on target; `sp_addlinkedserver` (`SQLOLEDB`, `@datasrc=<partner hostname>.<partner domain>`), `rpc`/`rpc out` true, `sp_addlinkedsrvlogin` `<NB>\scn-sql-link` → `sa` / `lab.hosts[partner].mssql.sa_password` | drop linked server (droplogins), drop login, reset config, remove AD user |
| `iis-upload` | `iis` / `[iis]` | copy `ad/GOAD/files/srv02/wwwroot/Default.aspx`, `Web.config`, `bin/` to `C:\inetpub\wwwroot\` (not `index.html`: Base `iis` role owns it); `win_file` `C:\inetpub\wwwroot\upload` directory; `win_acl` FullControl `IIS_IUSRS` on it | stop `DefaultAppPool` (`win_iis_webapppool state=stopped` or `Stop-WebAppPool` if available), remove `Default.aspx`, `Web.config`, `bin`, `upload`, start the pool |

- [ ] **Step 1:** extend `CATALOGUE`; `test_ad_tasks_delegate_to_dc(name)`: for every object scenario whose target capability lists a non-DC host in any Base lab (`esc*` with target `adcs`, `mssql-*`, `iis-upload`, `acl-genericall-group`, `local-admin`, `constrained-deleg-kerb`, `unconstrained-computer`, `rbcd`), every task whose PowerShell contains `-AD`, `AD:`, `[ADSI]`, or that includes `scenario_acl`, has `delegate_to` or `apply.delegate_to` equal to `{{ dc }}`. Run → FAIL (new packages) / Tasks 4–6 packages must already pass.
- [ ] **Step 2:** packages; READMEs `mssqlclient.py -windows-auth`, `exec_as_login sa`, `enum_links`, `use_link`; IIS webshell upload then `SeImpersonate`. **Step 3:** `pytest -q tests` → PASS. **Step 4:** commit `feat(scenarios): mssql and iis scenarios`.

---

### Task 8: Docs

- [ ] **Step 1:** `test_docs_list_every_scenario`: every folder in `scenarios/` appears as `` `name` `` in "Provided scenarios". Run → FAIL.
- [ ] **Step 2:** table (name, type, target, description); note domain-aware `esc9`/`rbcd` dependencies; "Disable" paragraph with the Disable contract (what is cleaned, accepted tooling residue). `pytest -q tests` → PASS. **Step 3:** commit `docs: scenario catalogue`.

---

### Task 9: Live disable harness

**Files:** Create `scripts/scenario_snapshot.ps1` (dev tool, not shipped to users' docs) and `tests/live/run_scenario_cycle.sh` (not collected by pytest: no `test_` prefix).

- `scenario_snapshot.ps1` prints a sorted, stable text snapshot of a host: on DCs `Get-ADObject -LDAPFilter '(name=scn-*)'` (domain + config NC), SDDL of domain root, AdminSDHolder, DC computer object and each lab computer (`userAccountControl`, `msDS-AllowedToDelegateTo`, `msDS-AllowedToActOnBehalfOfOtherIdentity`, `msDS-KeyCredentialLink`), WebServer template SDDL, `CN=OID` children, `CN=ForeignSecurityPrincipals` children, `Get-GPO -All` names, domain `gPLink`, `ms-DS-MachineAccountQuota`, computers with `mS-DS-CreatorSID`; on CA hosts `certutil -catemplates`, CA security (`certutil -getreg CA\Security`), `EditFlags`, `InterfaceFlags`; on every host local `Administrators` members, registry values behind every `base_setting` key, `SMB1Protocol` state, `WebDAV-Redirector` state, WSMan CredSSP; on MSSQL hosts `sys.server_principals` (name like `%scn-%`), `sys.servers`, msdb `sys.database_principals`, `xp_cmdshell`; on IIS hosts `C:\inetpub\wwwroot` listing.
- `run_scenario_cycle.sh <instance> <scenario> [host]`: snapshot all hosts → `uninstall.yml` directly on the clean lab (expect rc 0) → snapshot, diff must be empty → `enable_scenario` → run install a second time directly (rc 0) → `disable_scenario` → snapshot, diff with the first must be empty → `uninstall.yml` directly again (rc 0). Prints PASS/FAIL per step. Direct playbook runs use the same inventories as `AnsibleProvisioner.run_scenario` (lab inventory, `inventory_disable_vagrant`, `globalsettings.ini`, the instance's `scenario_run_inventory` content).

- [ ] **Step 1:** write both; run `run_scenario_cycle.sh 580b30-goad-mini-base-vmware kerberoast` → all PASS (existing scenario as harness self-test).
- [ ] **Step 2:** commit `test: live scenario disable harness`.

---

### Task 10: Live verification on GOAD-Mini-Base (instance `580b30-goad-mini-base-vmware`)

The instance was built before Task 2's keys: first run `provision_lab_from hardening.yml` so the new baselines are applied.

- [ ] **Step 1:** `list_scenarios all`: member_server / mssql / mssql_link / iis / forest_trust scenarios show the missing capability; all others available.
- [ ] **Step 2:** `run_scenario_cycle.sh` for every available scenario (DC-target and `adcs`), plus the README verification command between enable and disable. `acl-adminsdholder`: poll protected-object DACLs (Domain Admins, Administrator) every 5 min up to 60 min after disable.
- [ ] **Step 3:** cascade: enable `esc10-case1`, `esc9`; `disable_scenario esc10-case1` → refused listing `esc9@dc01`; `disable_scenario esc10-case1 --cascade` → both gone, snapshot diff empty.
- [ ] **Step 4:** ledger: PASS/FAIL per scenario; failures go back to the owning task, fix, rerun.

---

### Task 11: Live verification on GOAD-Base

Needs a GOAD-Base build (5 VMs). Same procedure as Task 10 for every scenario not verified there (member_server, mssql, mssql_link, iis, forest_trust targets, plus `rbcd` with `maq@dc02` and the domain-aware refusal with `maq@dc01`). Run only after the user confirms the build.
