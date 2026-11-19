# Vulnerability scenarios

Scenarios let you start from a hardened lab and switch individual vulnerabilities on and off, one at a time, from the GOAD console. They are only offered on labs that declare capabilities (the `-Base` labs).

## The -Base labs

| Lab | Based on |
|-----|----------|
| `GOAD-Base` | GOAD |
| `GOAD-Light-Base` | GOAD-Light |
| `GOAD-Mini-Base` | GOAD-Mini |

The `-Base` labs have the same machines and domains as their parent, but the vulnerabilities are removed. Their hardened baseline:

- Every domain account, every `domain_password` and every `local_admin_password` is `Aa1234567890!`.
- The `vagrant` user is disabled after provisioning. Scenarios are therefore provisioned as `administrator@<domain>` with `Aa1234567890!` (the `inventory_disable_vagrant` inventory).
- `ansible/hardening.yml` applies the `base_settings` declared per host in the lab `config.json` (SMB signing required, LDAP signing and channel binding, NTLMv2 only, LLMNR/NBT-NS/mDNS disabled, Defender and firewall on, print spooler disabled on DCs, machine account quota 0, ADCS web enrollment off, and so on).
- Admin accounts follow the Tier 0/1/2 model. Each domain has the groups `T0-Admins`, `T1-ServerAdmins` and `T2-WorkstationAdmins`. T0 is the Domain Admins (`cersei.lannister`, `robert.baratheon`, `eddard.stark`, `daenerys.targaryen`), who are also in `Protected Users` and marked sensitive. T1 is local Administrator on the member servers (`jeor.mormont` on srv02, `khal.drogo` on srv03). T2 is empty. Every other user has no admin rights. The `host.tier` setting enforces the logon restrictions (see below).
- `ansible/security.yml` enables LSA protection (RunAsPPL) on every host and the Defender ASR rule that blocks credential stealing from LSASS on member servers.
- The WebDAV client is not installed and no gMSA is created.

Each `-Base` lab declares `lab.capabilities` in its `config.json`: a map from a capability name to the hosts that provide it. Scenarios use capabilities to decide where they can run.

| Lab | Capabilities |
|-----|--------------|
| `GOAD-Base` | `adcs`: dc01, srv03; `mssql`: srv02, srv03; `child_domain`: dc02; `forest_trust`: dc01, dc03; `member_server`: srv02, srv03; `laps`: srv03; `iis`: srv02; `mssql_link`: srv02 |
| `GOAD-Light-Base` | `adcs`: dc01; `mssql`: srv02; `child_domain`: dc02; `member_server`: srv02; `iis`: srv02 |
| `GOAD-Mini-Base` | `adcs`: dc01 |

Existing labs (`GOAD`, `GOAD-Light`, `GOAD-Mini`, ...) are unchanged and have no scenarios.

## Commands

Run these in the GOAD console with an instance selected.

```
instance_id> list_scenarios [all]
instance_id> enable_scenario <name> [host] [--no-snapshot]
instance_id> disable_scenario <name> [host] [--cascade] [--no-snapshot]
instance_id> reset_scenarios
instance_id> list_snapshots
```

- `list_scenarios` shows enabled, dirty and available scenarios. With `all` it also lists unavailable scenarios and the reason (missing capability, conflict, missing dependency, ...).
- `enable_scenario` installs a scenario. Without `host`, the target is chosen automatically (see below).
- `disable_scenario` uninstalls it. If the scenario is enabled on several hosts you must name the host.
- `reset_scenarios` uninstalls every enabled scenario, dependents first.
- `show_credentials` prints every account of the current lab and its password: domain Administrators, domain users, each host's local Administrator, MSSQL `sa` logins, and the accounts created by enabled scenarios. It also works without a loaded instance, for the lab selected with `set_lab`.

### Targets

A scenario's identity is `name@target`, for example `esc8@dc01`.

- If the scenario declares a `target` capability, the target host is one of the hosts providing it. Without `host` the first one is used. With `host` it must provide the capability.
- If `target` is empty, the scenario runs on a domain controller. Without `host` the root DC is used. With `host` it must be a DC.

### Enable rules

`enable_scenario` is refused, with every reason printed, when:

- the lab has no `lab.capabilities`, or the scenario is unknown or not allowed on the lab (`labs`);
- a capability listed in `requires` is missing;
- the scenario is already enabled on the target;
- a scenario listed in `depends` is not enabled on a host of the target's domain (for example `rbcd` on srv02 needs `maq` enabled on dc02, the north DC, not on dc01);
- a scenario listed in `conflicts` (in either direction) is enabled;
- another enabled scenario on the same target host already changes one of its `touches` settings. A `touches` overlap is a conflict only on the same target host.

### Disable, cascade and dirty

- If other enabled scenarios in the same domain depend on the one you disable, the command is refused and lists them. Dependents in other domains are not affected. Use `--cascade` to uninstall the dependents first, then the scenario.
- If an install fails, the scenario is uninstalled again to clean up and is not recorded as enabled. If that cleanup also fails, the scenario is recorded as `dirty` so `disable_scenario` can retry it.
- If an uninstall fails, the scenario stays recorded and is marked `dirty`. The command stops there. Fix the cause and run `disable_scenario` again.

### Reset

`reset_scenarios` uninstalls all enabled scenarios in reverse dependency order and stops at the first failure (the failed one is marked `dirty`).

### Snapshots

On a VMware lab, goad can take a whole-lab snapshot before a scenario is applied and revert to it instead of
running the uninstall. A revert gives a lab that is clean after an attack, including the leftovers
`disable_scenario` does not clean.

- `enable_scenario` asks `Take a lab snapshot before enabling <scenario>@<host>? (y/N)`. On `y`, every VM is
  snapshotted as `scn-<seq>-<scenario>@<host>` (for example `scn-03-esc4@dc01`) before the install. If the
  snapshot fails, the scenario is not enabled.
- `disable_scenario` looks for that snapshot. When every VM has it, goad prints the snapshot order and what
  the revert changes, then asks `Revert the lab to <snapshot> instead of disabling? (y/N)`:

  ```
  lab snapshots (oldest first):
    scn-01-maq@dc02     for maq@dc02
    scn-02-rbcd@srv02   for rbcd@srv02  <- revert point
    scn-04-esc4@dc01    for esc4@dc01  deleted
  revert to scn-02-rbcd@srv02:
    removed:  rbcd@srv02
    lost:     esc1@dc01, esc4@dc01
    restored: smb-signing-off@srv02
  ```

  - `lost`: scenarios enabled after the snapshot. The revert removes them too, dependents included
    (`--cascade` only applies to the uninstall path).
  - `restored`: scenarios disabled after the snapshot. They are back in the lab and in `list_scenarios`.
  - Extensions installed after the snapshot are listed with their VMs: the revert destroys those VMs.
  - A change of the vagrant account (`vagrant account: enabled again`) is printed when the snapshot was taken
    before `disable_vagrant`.
- The revert restores every VM with `vmrun revertToSnapshot` and starts it again with `vmrun start`
  (`vagrant snapshot restore` would wait for the vagrant account, which is disabled on a provisioned `-Base`
  lab). Restored VMs resume with the clock of the snapshot, so goad then runs `ansible/sync_time.yml`, which
  sets every Windows clock from the controller's UTC time. If that fails goad warns: run the playbook by
  hand before attacking, Kerberos needs synced clocks.
- If the restore fails on some VMs, goad names the VMs it reverted and the ones it did not, and prints
  `lab partially reverted`. Run the same command again: the revert is offered again and finishes the job.
- A revert is not offered when the snapshot lists an extension you removed since (its VMs no longer exist).
- After a revert, `instance.json` holds the scenarios, extensions and vagrant state recorded with the
  snapshot. The revert-point snapshot and every later snapshot are deleted: they belong to a timeline that no
  longer exists.
- Answer `n` to keep the uninstall path. A scenario removed by uninstall (also by `reset_scenarios`) loses its
  snapshot.
- If an install fails and its cleanup fails too, the `dirty` scenario keeps its snapshot, so you can revert
  out of it.
- `list_scenarios` shows the snapshot of each enabled scenario.
- `list_snapshots` lists every snapshot goad recorded, oldest first: what it was taken for, the scenarios and
  extensions it captured, and whether every VM has it (`5/5` or `missing on <vm>`). Snapshots that VMware
  holds without a goad record are listed as `(no record)`; delete those by hand
  (`vagrant snapshot delete <vm> <name>`). The `push_*` snapshots of the old `snapshot` command are grouped in
  one `(old snapshot command)` row.
- No question is asked with `--no-snapshot`, or when the console does not run in a terminal (piped commands,
  `goad.py -t ...`): enable and disable then behave as without a snapshot.
- Only the VMware provider supports these snapshots.

#### snapshot / reset

On VMware, `snapshot [label]` takes a named, recorded lab snapshot `snap-<seq>-<label>` (`snap-<seq>-manual`
without a label) while the lab runs. You can take as many as you want; `list_snapshots` lists them with the
scenario and extension snapshots, and the state they captured.

`reset [snapshot]` first prints every snapshot, however it was taken. It then reverts to the snapshot named, or
to the latest one, after showing what the revert changes and asking `Reset the lab to <snapshot>? (y/N)` (no
question outside a terminal). Unlike a scenario revert, `reset` keeps the revert point and every later
snapshot, so you can reset to the same snapshot again. Restored instance state (scenarios, extensions, vagrant
account) and the clock resync work as for a scenario revert. With no named snapshot, `reset` falls back to the
last `push_*` snapshot of the old `snapshot` command.

Other providers keep the single `vagrant snapshot push` / `pop` snapshot.

### Re-provisioning

GOAD records in `instance.json` (`vagrant_disabled`) whether the vagrant account is currently disabled. The flag is set after a successful `disable_vagrant` and cleared after a successful `enable_vagrant`, whether run by the base lab flow or by hand. Provisioning a `-Base` lab again (including a new `install` on an existing instance) re-enables vagrant first when the flag is set, runs the full provisioning, disables vagrant again, then re-applies every enabled scenario in dependency order. The scenarios you enabled are therefore still in place after a re-provision.

## Package layout

Scenarios live in the top level `scenarios/` folder, one folder per scenario:

```
scenarios/<name>/
  scenario.json     metadata
  README.md         what it does, how to attack it, how to verify
  data/vars.yml     scenario variables
  ansible/
    install.yml     playbook that applies the scenario
    uninstall.yml   playbook that reverts it
```

Scenarios never merge into the lab data. They read their own `data/vars.yml`. Folders with an invalid `scenario.json` are skipped with a warning.

### scenario.json

| Field | Required | Description |
|-------|----------|-------------|
| `description` | yes | One line shown to the user. |
| `type` | yes | `object` or `setting` (see below). |
| `target` | no | Capability that provides the host to run on. Empty or missing: run on a domain controller. |
| `requires` | no | Capabilities the lab must declare. |
| `depends` | no | Scenarios that must already be enabled in the target's domain. |
| `conflicts` | no | Scenarios that cannot be enabled together with this one. |
| `touches` | no | Setting keys this scenario changes. Two scenarios touching the same key cannot be enabled on the same host. |
| `labs` | no | Lab names allowed. Defaults to `["*"]` (all labs with capabilities). |

### Object vs setting

- `object`: the scenario adds something to the lab, for example a user, an SPN or a certificate template (`kerberoast`, `asrep-roast`, `esc1`). Uninstall removes it.
- `setting`: the scenario flips a `base_settings` key to a vulnerable value (`esc8`, `llmnr`). Uninstall puts back the value declared for that host in the lab's `base_settings`, so the lab config remains the source of truth for the baseline. Settings scenarios should list the keys in `touches`.

## Provided scenarios

### Kerberos and delegation

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `kerberoast` | object | DC | Service account with an SPN, roastable. |
| `asrep-roast` | object | DC | User without Kerberos pre-authentication. |
| `rc4` | setting | DC | Kerberos RC4 allowed. |
| `constrained-deleg-any` | object | DC | Service account with constrained delegation and protocol transition to the DC (CIFS). |
| `constrained-deleg-kerb` | object | `member_server` | Member server computer account with Kerberos-only constrained delegation to HTTP on the DC. |
| `unconstrained-computer` | object | `member_server` | Member server trusted for unconstrained delegation. |
| `unconstrained-user` | object | DC | Service account trusted for unconstrained delegation. |
| `rbcd` | object | `member_server` | User with GenericWrite on a member server computer account (resource-based constrained delegation). Depends on `maq` (same domain). |
| `writespn` | object | DC | User that can write the servicePrincipalName of another user (targeted kerberoast). |

### ADCS

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `esc1` | object | `adcs` | Certificate template where the enrollee supplies the subject, enrollable by Domain Users. |
| `esc2` | object | `adcs` | Certificate template with the Any Purpose EKU, enrollable by Domain Users (ESC2). |
| `esc3` | object | `adcs` | Enrollment agent template plus a template that accepts enrollment agents (ESC3). |
| `esc4` | object | `adcs` | Certificate template writable by a low-privileged user (ESC4). |
| `esc6` | setting | `adcs` | CA flag EDITF_ATTRIBUTESUBJECTALTNAME2 (enrollee-supplied SAN on any template, ESC6). |
| `esc7` | object | `adcs` | Low-privileged user with ManageCA on the CA (ESC7). |
| `esc8` | setting | `adcs` | ADCS web enrollment over HTTP with NTLM, no EPA. |
| `esc9` | object | `adcs` | Template without the security extension, plus GenericWrite on a user (ESC9). Depends on `esc10-case1` (same domain). |
| `esc10-case1` | setting | DC | KDC weak certificate binding (StrongCertificateBindingEnforcement 0, ESC10 case 1). |
| `esc10-case2` | setting | DC | Schannel maps certificates by UPN (CertificateMappingMethods 0x4, ESC10 case 2). |
| `esc11` | setting | `adcs` | CA accepts unencrypted ICertPassage requests (IF_ENFORCEENCRYPTICERTREQUEST off, ESC11). |
| `esc13` | object | `adcs` | Template with an issuance policy linked to a privileged group (ESC13). |
| `esc15` | object | `adcs` | Domain Users can enroll in the schema v1 Web Server template (ESC15). |

### ACL

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `acl-forcechangepassword` | object | DC | User that can reset another user's password (ForceChangePassword). |
| `acl-genericwrite-user` | object | DC | User with GenericWrite on another user. |
| `acl-writedacl-user` | object | DC | User with WriteDacl on another user. |
| `acl-self-membership` | object | DC | User that can add itself to a group (Self-Membership). |
| `acl-addmember` | object | DC | User that can write the member attribute of a group (AddMember). |
| `acl-writeowner` | object | DC | User with WriteOwner on a group. |
| `acl-genericall-user` | object | DC | User with GenericAll on another user. |
| `acl-genericall-computer` | object | DC | User with GenericAll on a domain controller computer object. |
| `acl-genericall-group` | object | `member_server` | User with GenericAll on a group that is local administrator of a member server. |
| `acl-adminsdholder` | object | DC | User with GenericAll on AdminSDHolder (persistence on every protected object). |
| `acl-writedacl-ou` | object | DC | User with WriteDacl on an OU (inheritable control over its objects). |
| `acl-writeproperty` | object | DC | User with WriteProperty (all properties) on another user. |
| `anonymous-rpc` | object | DC | Anonymous read on the domain root (anonymous RPC/SAMR enumeration). |
| `gpo-abuse` | object | DC | User that can edit a GPO linked to the domain root. |
| `foreign-group-acl` | object | `forest_trust` | Group with a member from the trusted forest that has GenericAll on a domain controller. |
| `local-admin` | object | `member_server` | Ordinary domain user that is local administrator of a member server. |

### Network, relay and coercion

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `llmnr` | setting | `member_server` | LLMNR and NBT-NS enabled on a host. |
| `mdns` | setting | `member_server` | mDNS enabled on a member server. |
| `smb-signing-off` | setting | `member_server` | SMB signing not required on a member server. |
| `smbv1` | setting | `member_server` | SMBv1 enabled on a member server. |
| `ntlm-downgrade` | setting | DC | DC accepts LM and NTLMv1 (LmCompatibilityLevel 2). |
| `ldap-signing-off` | setting | DC | DC does not require LDAP signing. |
| `ldap-cbt-off` | setting | DC | DC does not enforce LDAPS channel binding. |
| `printerbug` | setting | DC | Print Spooler running on the DC (PrinterBug coercion). |
| `webdav` | setting | `member_server` | WebDAV client (WebClient service) installed and running on a member server. |
| `credssp` | setting | `member_server` | WinRM CredSSP server role enabled on a member server. |
| `maq` | setting | DC | Machine account quota 10: any domain user can create computer accounts. |

### Host

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `defender-off` | setting | `member_server` | Defender real-time protection off on a member server. |
| `firewall-off` | setting | `member_server` | Windows firewall off on a member server. |

### Trust

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `sid-history` | setting | `forest_trust` | SID history accepted on the forest trust. |

### MSSQL and web

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `mssql-impersonate-login` | object | `mssql` | SQL login that can impersonate sa. |
| `mssql-impersonate-user` | object | `mssql` | SQL login that can impersonate dbo in msdb (TRUSTWORTHY). |
| `mssql-sysadmin` | object | `mssql` | Domain user that is sysadmin on SQL Server (xp_cmdshell as the service account). |
| `mssql-linked` | object | `mssql_link` | Linked server to the SQL Server of the other forest, mapped to its sa. |
| `iis-upload` | object | `iis` | IIS site with an unrestricted file upload page (webshell). |

Each package has a `README.md` with the attack, a verification step, and what disable removes.

Dependencies are checked per domain. For example `rbcd` on srv02 (north) needs `maq` enabled on dc02 (`enable_scenario maq dc02`), and `esc9` on a CA needs `esc10-case1` enabled on the DC of the CA's domain.

### What disable cleans

Disable returns the lab to its Base state for everything the scenario owns: objects it created (all named `scn-*`), access rights and attributes it added to lab objects, settings it changed, files it copied. It also cleans the cheap attack leftovers: certificates issued from a scenario template are revoked, computer accounts created through the machine account quota are deleted (`maq`, `rbcd`, `acl-genericall-computer`), shadow credentials and RBCD written on lab computer objects are cleared, and `xp_cmdshell` is turned off again. What a scenario does not clean (for example GPO settings already applied to hosts, or secrets dumped during the attack) is listed in its README.

Tooling installed by scenarios stays: the `ADCSTemplate` PowerShell module, `C:\setup\*.json`, the PSPKI module and the NuGet provider.

## base_settings keys

`base_settings` is declared per host in the lab `config.json` (`lab.base_settings.<host>.<key>`). The `base_setting` role (`ansible/roles/base_setting`) applies one key and asserts the value is accepted. An invalid value fails the play.

| Key | Accepted values |
|-----|-----------------|
| `net.llmnr` | `disabled`, `enabled` |
| `net.nbtns` | `disabled`, `enabled` |
| `net.mdns` | `disabled`, `enabled` |
| `smb.signing` | `required`, `optional` |
| `kerberos.rc4` | `disabled`, `enabled` |
| `ntlm.lmcompat` | `0` to `5` |
| `defender.realtime` | `on`, `off` |
| `firewall.state` | `on`, `off` |
| `ldap.signing` | `required`, `none` |
| `ldap.channel_binding` | `always`, `never` |
| `dc.maq` | `0` to `10` |
| `host.tier` | `0`, `1`, `2` |
| `dc.cert_mapping` | `absent`, `0x4` |
| `smb.v1` | `disabled`, `enabled` |
| `winrm.credssp` | `disabled`, `server`, `client` |
| `trust.sid_history` | `disabled`, `enabled` |
| `net.webclient` | `absent`, `present` |
| `dc.spooler` | `disabled`, `enabled` |
| `dc.strong_cert_binding` | `0`, `1`, `2` |
| `adcs.web_enrollment` | `true`, `false` |
| `adcs.editf_san` | `off`, `on` |
| `adcs.enforce_encrypt` | `on`, `off` |

`host.tier` applies the tier model's logon restrictions on a host with deny user rights. The groups listed are the tier groups (`T0-Admins`, `T1-ServerAdmins`, `T2-WorkstationAdmins`) of every domain of the lab:

| Tier | Deny log on locally, through RDP, as a batch job, as a service | Deny access from the network |
|------|------|------|
| `0` (DCs) | T1, T2 | nobody |
| `1` (member servers) | T0, T2 | T2 |
| `2` (workstations) | T0, T1 | T0, T1 |

Nobody is denied network logon on a DC, because every account needs LDAP, SYSVOL and Group Policy there. T0 keeps network logon on tier 1 because GOAD provisions member servers as a domain admin over WinRM. The built-in `Administrator` is in no tier group, so it is never restricted.

`kerberos.rc4` also sets `msDS-SupportedEncryptionTypes` on every trust object (`objectClass=trustedDomain` under `CN=System,<domain DN>`) when it runs on a DC: `24` (AES128 + AES256) for `disabled`, `28` (RC4 + AES) for `enabled`. Without it, inter-realm referrals across the `sevenkingdoms.local` / `essos.local` forest trust fall back to RC4 and fail once RC4 is disabled. This has not yet been checked on a live lab. To check it on `GOAD-Base`, log on as a `sevenkingdoms.local` user and run `klist get cifs/meereen.essos.local`: it must return an AES ticket.

## How to write a scenario

The `esc8` scenario is the smallest complete example of a `setting` scenario.

### 1. scenario.json

```json
{
  "description": "ADCS web enrollment over HTTP with NTLM, no EPA",
  "type": "setting",
  "requires": ["adcs"],
  "target": "adcs",
  "touches": ["adcs.web_enrollment"]
}
```

It needs the `adcs` capability, runs on a host providing `adcs`, and declares that it changes `adcs.web_enrollment`.

### 2. data/vars.yml

```yaml
touched_settings:
  - key: adcs.web_enrollment
    vulnerable_value: true
```

### 3. ansible/install.yml

```yaml
---
- import_playbook: "../../../ansible/data.yml"
  vars:
    data_path: "../ad/{{domain_name}}/data/"
  tags: 'data'

- name: "Install esc8 scenario"
  hosts: scenario_target
  vars_files:
    - ../data/vars.yml
  vars:
    domain: "{{ lab.hosts[scenario_target].domain }}"
    domain_username: "{{ domain }}\\administrator"
    domain_password: "{{ lab.domains[domain].domain_password }}"
  tasks:
    - name: "Apply install value for each touched setting"
      ansible.builtin.include_role:
        name: "{{ playbook_dir }}/../../../ansible/roles/base_setting"
      vars:
        setting_key: "{{ scenario_setting.key }}"
        setting_value: "{{ scenario_setting.vulnerable_value }}"
      loop: "{{ touched_settings }}"
      loop_control:
        loop_var: scenario_setting
```

Points to note:

- `hosts: scenario_target`. GOAD writes an inventory with a `[scenario_target]` group that contains only the chosen host, plus the vars `scenario_name` and `scenario_target`. It is added after the `inventory_disable_vagrant` inventory (and the inventories of enabled extensions), so connections use `administrator`.
- `import_playbook: ../../../ansible/data.yml` loads the lab data (`lab`, `lab.hosts`, `lab.domains`, `lab.base_settings`), as the lab playbooks do.
- `domain`, `domain_username` and `domain_password` are the variables the `base_setting` role expects.
- `include_role` applies each key of the `base_setting` role with `setting_key` and `setting_value`. The role is referenced by path from `playbook_dir`: the playbook runs from `scenarios/<name>/ansible`, where Ansible does not search `ansible/roles`, so a bare `name: base_setting` fails with "the role 'base_setting' was not found".

### 4. ansible/uninstall.yml

Identical, except the value comes from the lab baseline:

```yaml
        setting_value: "{{ lab.base_settings[scenario_target][scenario_setting.key] }}"
```

This is what makes disable restore the declared baseline for that host.

### 5. README.md

Describe what the scenario does, how to attack it and how to check that it is enabled.

For an `object` scenario (see `kerberoast`), install adds the object and uninstall removes it. Use the same `hosts: scenario_target` header. Make both playbooks idempotent, because install is re-run on re-provisioning and uninstall is also run to clean up after a failed install.

### Shared roles for object scenarios

Object scenarios use three roles from `ansible/roles`, included by path like `base_setting`. Each runs its AD work on the DC of the scenario's domain (`delegate_to: "{{ dc }}"`), so a playbook must define `dc: "{{ lab.domains[domain].dc }}"`. AD work has to run there because a member server target (srv02, the srv03 CA) has no AD PowerShell module.

- `scenario_ad` (`tasks_from: users` or `groups`, `ad_state: present|absent`): creates or deletes `scn-*` users and groups in `CN=Users`.
- `scenario_acl` (`tasks_from: add` or `remove`): adds or removes one explicit Allow ACE. Set `acl_principal`, `acl_target_dn`, `acl_right` and `acl_inheritance`. The target DN can use `%DOMAIN%`, `%CONFIG%` or `sam:<account>`. Remove takes away only the rights bits the scenario added, even when Windows merged them into another ACE.
- `scenario_adcs_template` (`tasks_from: add` or `remove`): creates and publishes a template from `ansible/roles/adcs_templates/files`. Remove revokes the certificates issued from the template, unpublishes it and deletes it.

Do not pass a role variable as `x: "{{ x }}"` in an include: that is a recursive template at run time. The play variable of the same name is already visible to the role.

To test a new scenario, run `list_scenarios` (it should appear as `available`), then `enable_scenario <name>`, verify, then `disable_scenario <name>` and verify the baseline is back.
