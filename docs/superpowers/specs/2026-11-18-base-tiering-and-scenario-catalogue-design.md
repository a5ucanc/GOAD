# Base lab tiering + full scenario catalogue — design

Date: 2026-11-18
Status: approved
Builds on: `2026-11-17-vuln-scenarios-design.md`

## Intent

The `-Base` labs (`GOAD-Base`, `GOAD-Light-Base`, `GOAD-Mini-Base`) are meant to be a clean,
hardened AD that scenarios switch single vulnerabilities on and off in. A scan of the repo
showed two problems:

1. The baseline still leaks. Non-Domain-Admin users sit in `BUILTIN\Administrators` on DCs
   (`robb.stark`, `catelyn.stark` on dc02, `DragonRider` on dc01, `greatmaster` on dc03),
   the WebDAV client is installed on srv02/srv03, and the host security roles
   (`security.yml`) are not applied at all.
2. Only five scenarios exist (`kerberoast`, `asrep-roast`, `esc1`, `esc8`, `llmnr`), while
   the vulnerable labs configure ~45 vulnerabilities.

The user wants the baseline rebuilt on the classic tier model and every remaining
configured vulnerability ported to a scenario, except bots, secrets and passwords.

## Goals

- Base labs follow the Tier 0/1/2 admin model, enforced per host.
- WebDAV client is no longer installed on Base labs.
- `security.yml` runs on Base labs with a hardening-only role set.
- Base provisioning is trimmed of playbooks that do nothing on Base.
- A scenario package exists for every catalogue entry in "Scenario catalogue" below.

## Non-goals

- Passwords. Every account keeps `Aa1234567890!`; password policy stays as `ad-data.yml`
  sets it. (Already done separately: `dc.maq: 0` on every Base DC.)
- Scenarios for bots (scheduled-task coercion/RDP/CredSSP bots), secrets (SYSVOL scripts,
  share loot, Credential Manager, autologon, gMSA read, LAPS read) and passwords
  (password in description, weak passwords, password policy).
- Changing the original labs or extensions (`GOAD`, `GOAD-Light`, `GOAD-Mini`, `ws01`,
  `lx01`, `exchange`, ...). `test_original_labs_untouched` must keep passing.
- Authentication Policy Silos, tier OUs and tier GPOs (approach B/C, rejected).
- NHA / DRACARYS / SCCM / MINILAB-only vulnerabilities (NHA `SignatureValidation`
  template, DRACARYS bots, SCCM).
- Exchange PrivExchange (extension only, not on Base).
- Upgrading already-deployed Base instances in place (user decision). The Part 1 changes are
  config removals that existing roles do not undo (`adjust_rights` only adds, an empty
  `[webdav]` group does not uninstall WebClient). Existing instances get the new baseline by
  rebuilding. No cleanup tasks, no live re-provision test for Part 1.
- `tier-violation` scenario (user decision): without a T0 logon on the host (a bot, out of
  scope) it exposes nothing. Revisit with bots.

## Anti-goals

- Tier enforcement locking out the provisioning account. Ansible connects and `runas`-becomes
  as `<domain>\administrator`; that must keep working on every host.
- A scenario leaving residue after disable (inherited from the scenario design).
- A Base lab carrying a misconfiguration without a scenario enabled.

## Approaches considered (tier enforcement)

- **A. Data + per-host user rights via a `base_setting` key (picked).** Tier groups in
  `config.json`, `host.tier` key applies deny logon rights with `win_user_right`. Reuses the
  `base_setting`/`touches` machinery, so a scenario can flip a host's tier enforcement.
  Not visible as a GPO.
- B. Tier OUs + one GPO per tier. Realistic and visible in BloodHound, but needs a new GPO
  role and scenario toggles mean editing GPOs and waiting for refresh.
- C. B + Authentication Policy Silos for T0. Strongest, but needs Kerberos armoring, is
  fragile to provision and blocks several planned scenarios (delegation, ESC to DA).

## Part 1 — Base hardening

### 1.1 Tier model (reuse GOAD characters)

Per domain, new global groups in `CN=Users`:

| Group | Members | Admin on |
|-------|---------|----------|
| `T0-Admins` | sevenkingdoms: `cersei.lannister`, `robert.baratheon`; north: `eddard.stark`; essos: `daenerys.targaryen` | DCs (via `Domain Admins` membership) |
| `T1-ServerAdmins` | north: `jeor.mormont`; essos: `khal.drogo` | member servers (local `Administrators`) |
| `T2-WorkstationAdmins` | empty | workstations (none on Base) |

- T0 members stay in `Domain Admins`. `T0-Admins` is a separate group so deny rights can
  target named humans without hitting the built-in `Administrator` (RID 500), which is the
  provisioning/break-glass account and is exempt from all tier restrictions.
- T0 members are added to `Protected Users` and get `AccountNotDelegated`
  (`account_is_sensitive`). `Administrator` is not added (Protected Users breaks NTLM, which
  the WinRM connection uses).
- `local_groups` on Base:
  - DCs: `Administrators` entries removed (domain admins already have it).
    `Remote Desktop Users` removed.
  - srv02: `Administrators: [north\T1-ServerAdmins]`. `Remote Desktop Users` kept for
    ordinary user groups (benign, RDP is not admin).
  - srv03: `Administrators: [essos\T1-ServerAdmins]`, `Remote Desktop Users` kept.
- Every other user becomes an ordinary user with no admin rights anywhere.
- `DragonRider` and `greatmaster` stay as plain groups.
- GOAD-Light-Base / GOAD-Mini-Base: same, restricted to the domains and hosts they have.

Cross-domain: T0 deny lists include the T0 groups of every domain in the lab's forest set
(e.g. on srv02 deny `NORTH\T0-Admins`, `SEVENKINGDOMS\T0-Admins`, `ESSOS\T0-Admins`). Only
groups of domains that exist in that lab are listed.

### 1.2 `host.tier` base setting

New key `host.tier`, values `0`, `1`, `2`. Task file `host_tier.yml`.

Applied on every Base host: DCs `0`, member servers `1`.

| Host tier | Deny `SeDenyInteractiveLogonRight`, `SeDenyRemoteInteractiveLogonRight`, `SeDenyBatchLogonRight`, `SeDenyServiceLogonRight` | Deny `SeDenyNetworkLogonRight` |
|-----------|------|------|
| `0` | T1 + T2 groups | none |
| `1` | T0 + T2 groups | T2 groups only |
| `2` | T0 + T1 groups | T0 + T1 groups |

- Nobody is denied network logon on DCs (builder check, my call): every account needs LDAP,
  SMB/SYSVOL and GPO processing against DCs, and T1 admins have no separate user account.
- T0 is not denied network logon on tier-1 hosts: Microsoft guidance does, but the scenario
  engine and the existing roles reach member servers as a domain admin over WinRM and
  `runas`. Recorded as a deliberate deviation. The built-in `Administrator` is never listed.
- `win_user_right` with `action: add` / `remove`, so only the tier groups are touched and
  other principals in those rights stay.
- The group names come from the lab data (list of domains for the host's lab), not
  hardcoded.
- Tier groups must exist before `hardening.yml`: they are created by `ad-data.yml` from
  `config.json` like any other group.

### 1.3 `security.yml` on Base

Add `security.yml` to the three Base entries of `playbooks.yml`, before `hardening.yml`
(`security.yml` toggles Defender through the `defender_on` group; `hardening.yml` must win).

Per-host `security` lists in Base `config.json`:

| Role | Hosts | Notes |
|------|-------|-------|
| `enable_run_as_ppl` | all | LSA protection |
| `asr` | member servers | only rule `9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2` (block LSASS credential stealing) |
| `account_is_sensitive` | root DC of each domain | `security_vars` lists the T0 members of that domain |

Excluded: `maq0_client`, `maq0_server` (they weaken NTLM session security despite the name),
`powershell_restrict` (only sets execution policy, no value), ASR "PSExec and WMI" rule
(breaks post-exploitation steps of many scenarios), `ldaps`, `files`, `directory`.

`test_playbooks_entry_has_no_vuln_playbooks` is updated to allow `security.yml` and to
assert no Base host lists `maq0_*`.

### 1.4 WebDAV removed

Empty the `[webdav]` group in the three Base `inventory` files. `servers.yml` still runs for
iis/mssql. The `webdav` scenario (below) installs the client when enabled.

### 1.5 Provisioning trims

- Drop `ad-gmsa.yml` from Base entries (no `gmsa` in Base config).
- Keep `wait5m.yml` (child-domain timing), `laps.yml` (`laps` capability on srv03).
- New tests: Base `playbooks.yml` entries contain no playbook whose host group is empty in
  that lab's inventory.

### 1.6 Capabilities added

| Capability | GOAD-Base | GOAD-Light-Base | GOAD-Mini-Base |
|------------|-----------|-----------------|----------------|
| `iis` | srv02 | srv02 | — |
| `mssql_link` | srv02 | — | — |
| `forest_trust` | (exists) dc01, dc03 | — | — |

`mssql_link` means "mssql host with a second mssql host reachable across a trust"; the
linked partner is the other `mssql` host.

### 1.7 Domain-aware `depends` (engine change)

Today `ScenarioResolver.check_enable` (`goad/scenario_resolver.py`) accepts a dependency
enabled on any host. With several domains that is wrong: `rbcd@srv02` (north) would pass
with `maq@dc01` (sevenkingdoms) while north MAQ stays 0. User decision: dependencies are
domain-aware.

- A dependency `d` of scenario `s` enabled on target `t` is met only when `d` is enabled on
  a host whose domain (`lab.hosts[h].domain`) equals the domain of `t`.
- Refusal reason: `requires scenario <d> in domain <domain>`, so the user knows to run e.g.
  `enable_scenario maq dc02`.
- `dependents()` (used by `disable_scenario` refusal and `--cascade`) uses the same rule:
  disabling `maq@dc01` does not list `rbcd@srv02`.
- `install_order()` / `reset_scenarios` / re-provision ordering keep working on names; same
  domain filtering applies wherever an entry is matched to its dependency.
- The resolver needs the host-to-domain map from the lab config, passed in where it is
  built. Unit tests cover: same-domain met, other-domain refused, cascade per domain.
- `docs/mkdocs/docs/scenarios.md` "Enable rules" and "Disable, cascade" updated.

## Part 2 — Scenario catalogue

All packages follow `docs/mkdocs/docs/scenarios.md`. `Target` empty = DC. Every package gets
`scenario.json`, `README.md` (attack + verification), `data/vars.yml`,
`ansible/install.yml`, `ansible/uninstall.yml`. All install/uninstall playbooks are
idempotent.

### 2.1 Setting scenarios on existing keys

| Scenario | touches → vulnerable value | target | requires |
|----------|----------------------------|--------|----------|
| `smb-signing-off` | `smb.signing: optional` | `member_server` | `member_server` |
| `ntlm-downgrade` | `ntlm.lmcompat: 2` | DC | — |
| `ldap-signing-off` | `ldap.signing: none` | DC | — |
| `ldap-cbt-off` | `ldap.channel_binding: never` | DC | — |
| `printerbug` | `dc.spooler: enabled` | DC | — |
| `esc10-case1` | `dc.strong_cert_binding: 0` | DC | `adcs` |
| `esc6` | `adcs.editf_san: on` | `adcs` | `adcs` |
| `esc11` | `adcs.enforce_encrypt: off` | `adcs` | `adcs` |
| `rc4` | `kerberos.rc4: enabled` | DC | — |
| `mdns` | `net.mdns: enabled` | `member_server` | `member_server` |
| `defender-off` | `defender.realtime: off` | `member_server` | `member_server` |
| `firewall-off` | `firewall.state: off` | `member_server` | `member_server` |
| `maq` | `dc.maq: 10` | DC | — |

### 2.2 Setting scenarios needing new keys

| Scenario | New key, values (baseline first) | target | Source |
|----------|----------------------------------|--------|--------|
| `esc10-case2` | `dc.cert_mapping`: `0x18`, `0x4` (`HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\Schannel\CertificateMappingMethods`) | DC, requires `adcs` | `vulns/adcs_esc10_case2` |
| `smbv1` | `smb.v1`: `disabled`, `enabled` | `member_server` | `vulns/smbv1` |
| `credssp` | `winrm.credssp`: `disabled`, `server`, `client` | `member_server` | `vulns/enable_credssp_*` |
| `sid-history` | `trust.sid_history`: `disabled`, `enabled` | `forest_trust` | `GOAD/scripts/sidhistory.ps1` |
| `webdav` | `net.webclient`: `absent`, `present` (WebDAV-Redirector feature + WebClient service) | `member_server` | `ansible/roles/webdav` |

New keys are added to every relevant host's `base_settings` with the baseline value, to the
test `ACCEPTED` map and to the docs key table. The baseline value for `dc.cert_mapping` must
be checked on a live DC before it is written (the Windows default after KB5014754 is `0x18`).

### 2.3 ADCS object scenarios

All `type: object`, `target: adcs`, `requires: [adcs]`. Templates reuse the JSON in
`ansible/roles/adcs_templates/files` and the `esc1` install pattern. Template enrollment
rights go to `Domain Users` unless stated.

| Scenario | Object | Source |
|----------|--------|--------|
| `esc2` | template `ESC2` (Any Purpose EKU) | `ESC2.json` |
| `esc3` | templates `ESC3-CRA` (enrollment agent) + `ESC3` | `ESC3-CRA.json`, `ESC3.json` |
| `esc4` | template `ESC4` + GenericAll for a scenario user | `ESC4.json`, `GenericAll_khal_esc4` |
| `esc7` | ManageCA granted to a scenario user | `vulns/adcs_esc7` |
| `esc9` | template `ESC9` (no security extension) + GenericWrite on a victim user | `ESC9.json` |
| `esc13` | template `ESC13` with issuance policy OID linked to a privileged group | `vulns/adcs_esc13` |
| `esc15` | `Domain Users` enroll on the `Web Server` template (schema v1) | `vulns/adcs_esc15` |

`esc9` conflicts with nothing at the template level but only works with
`dc.strong_cert_binding` below `2`: it `depends: ["esc10-case1"]`.
Scenario users are created by the package with password `Aa1234567890!` and removed on
uninstall (same as `kerberoast`).

### 2.4 Delegation object scenarios

| Scenario | Object | target | requires / depends |
|----------|--------|--------|--------------------|
| `constrained-deleg-any` | user with SPN, `TrustedToAuthForDelegation`, `msDS-AllowedToDelegateTo` CIFS/<DC> | DC | — |
| `constrained-deleg-kerb` | target host computer account gets `msDS-AllowedToDelegateTo` HTTP/<DC> | `member_server` | `member_server` |
| `unconstrained-computer` | target host computer account `TrustedForDelegation` | `member_server` | `member_server` |
| `unconstrained-user` | user with SPN and `TrustedForDelegation` | DC | — |
| `rbcd` | scenario user with GenericWrite on the target host computer object | `member_server` | `member_server`; `depends: [maq]` |
| `writespn` | scenario user with Validated-SPN write on another scenario user | DC | — |

Uninstall clears exactly the attributes/ACEs set (computer accounts are never deleted).

### 2.5 ACL object scenarios

One package per primitive. Each creates its own principal and target objects (prefixed
`scn-<scenario>-`), applies one ACE, and removes both on uninstall. A shared role
`ansible/roles/scenario_acl` (create principal/target, add/remove ACE) is used by all of them.

| Scenario | Right | Target object | Source |
|----------|-------|---------------|--------|
| `acl-forcechangepassword` | `Ext-User-Force-Change-Password` | user | tywin→jaime |
| `acl-genericwrite-user` | `GenericWrite` | user | jaime→joffrey |
| `acl-writedacl-user` | `WriteDacl` | user | joffrey→tyron |
| `acl-self-membership` | `Ext-Self-Self-Membership` | group | tyron→Small Council |
| `acl-addmember` | `Ext-Write-Self-Membership` (inheritance All) | group | Small Council→DragonStone |
| `acl-writeowner` | `WriteOwner` | group | DragonStone→KingsGuard |
| `acl-genericall-user` | `GenericAll` | user | KingsGuard→stannis |
| `acl-genericall-computer` | `GenericAll` | DC computer object | stannis→kingslanding$ |
| `acl-genericall-group` | `GenericAll` | scenario-created group that is local `Administrators` on a member server | varys |
| `acl-adminsdholder` | `GenericAll` | `CN=AdminSDHolder` | varys |
| `acl-writedacl-ou` | `WriteDacl` | OU (scenario-created) | renly→Crownlands |
| `acl-writeproperty` | `WriteProperty` (inheritance All) | user | viserys→jorah |
| `anonymous-ldap` | `ReadProperty`+`GenericExecute` for `ANONYMOUS LOGON` on domain root | domain | north `anonymous_rpc` |
| `gpo-abuse` | GPO linked to domain root, `GpoEditDeleteModifySecurity` for a scenario user | GPO | `gpo_abuse.ps1` |
| `foreign-group-acl` | domain-local group in domain A containing a user of domain B, `GenericAll` on a domain-A computer | DC of domain A | `GenericAll_group_acrrosdom_dc`; `requires: [forest_trust]`, `target: forest_trust` |
| `local-admin` | ordinary scenario user added to local `Administrators` of a member server | `member_server` | `local_groups` |

Principals are always scenario-created. Targets are scenario-created too, except the built-in
objects named above (a DC computer object, `CN=AdminSDHolder`, the domain root); on those,
uninstall removes only the ACE. GOAD characters in the Source column only show where the
primitive came from (builder check, my call).

`acl-genericall-group` does not target `Domain Admins`: it is AdminSDHolder-protected, so a
lone ACE is reverted by SDProp within 60 minutes (builder check, my call).

`acl-adminsdholder` uninstall must also wait for / force SDProp so the ACE disappears from
protected objects (or document that it lingers until the next SDProp run, max 60 min).

### 2.6 MSSQL object scenarios

All `target: mssql`, `requires: [mssql]`. Use the `mssql` vulns role's SQL-command task.

| Scenario | Object | Source |
|----------|--------|--------|
| `mssql-impersonate-login` | scenario login with `IMPERSONATE` on `sa` | `executeaslogin` |
| `mssql-impersonate-user` | scenario user in `msdb` with `IMPERSONATE` on `dbo` (msdb is TRUSTWORTHY) | `executeasuser` |
| `mssql-sysadmin` | domain scenario user granted `sysadmin` (xp_cmdshell → service account → SeImpersonate) | `sysadmins` |
| `mssql-linked` | linked server to the other `mssql` host with login mapped to `sa` | `linked_servers`; `target: mssql_link`, `requires: [mssql_link]` (GOAD-Base only) |

### 2.7 Web

| Scenario | Object | target |
|----------|--------|--------|
| `iis-upload` | upload page from `ad/GOAD/files/srv02/wwwroot` + `IIS_IUSRS` FullControl on `C:\inetpub\wwwroot\upload` | `iis`, `requires: [iis]` |

Uninstall removes the page and the folder. The site source is read from `ad/GOAD/files`
(read-only use of the original lab).

## Constraints found in the codebase

- `base_setting` task file names map to keys by replacing only the first `_`
  (`tests/test_scenario_packages.py`): new keys must have a dot after their first segment
  only (`host.tier` → `host_tier.yml`, `net.webclient` → `net_webclient.yml`).
- Scenario playbooks run from `scenarios/<name>/ansible`; roles are referenced by path from
  `playbook_dir`.
- Scenarios connect as `<domain>\administrator` via `inventory_disable_vagrant`; that
  account must stay exempt from tier deny rights.
- `ad-relations.yml` applies `local_groups` with `settings/adjust_rights` + `user_rights`.

## Delivery order

1. Part 1 (Base hardening, incl. 1.7 engine change) — scenarios depend on its users,
   rights and domain-aware `depends`.
2. 2.1 + 2.2 setting scenarios (new keys land here).
3. 2.3 ADCS.
4. 2.4 delegation + 2.5 ACL (+ `scenario_acl` role).
5. 2.6 MSSQL + 2.7 IIS.
6. Docs: `scenarios.md` provided-scenarios table, key table, capabilities table.

Each step ends with the unit tests green. Live-lab verification (enable → verify → disable →
baseline back) is done per scenario on GOAD-Base; GOAD-Light-Base / Mini-Base only for
scenarios whose capabilities they have.

## Left to the builder

- Exact scenario user / object names (keep the `scn-` prefix convention).
- Whether `scenario_acl` is a role or a task file include.
- README wording.
