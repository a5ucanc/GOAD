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
instance_id> enable_scenario <name> [host]
instance_id> disable_scenario <name> [host] [--cascade]
instance_id> reset_scenarios
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

| Scenario | Type | Target | Description |
|----------|------|--------|-------------|
| `kerberoast` | object | DC | Service account with an SPN, roastable |
| `asrep-roast` | object | DC | User without Kerberos pre-authentication |
| `esc1` | object | `adcs` | Certificate template where the enrollee supplies the subject, enrollable by Domain Users |
| `esc8` | setting | `adcs` | ADCS web enrollment over HTTP with NTLM, no EPA |
| `llmnr` | setting | `member_server` | LLMNR and NBT-NS enabled on a host |

Each package has a `README.md` with the attack and a verification step.

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

To test a new scenario, run `list_scenarios` (it should appear as `available`), then `enable_scenario <name>`, verify, then `disable_scenario <name>` and verify the baseline is back.
