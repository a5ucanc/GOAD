# Toggleable vulnerability scenarios + Kali extension — design

Date: 2026-11-17
Status: draft, pending approval
Audience: security researchers

## Intent

Today every GOAD lab ships with its vulnerabilities baked into `ad/<LAB>/data/config.json`
and a handful of playbooks (`vulnerabilities.yml`, `ad-acl.yml`, `adcs.yml`, `security.yml`,
mssql roles). The user wants to run **training scenarios that can be toggled on and off on a
live lab**. The audience is always a security researcher, never a trainee: every
credential is known by design and initial access is out of scope. Start from a clean, hardened AD, plug in exactly the vulnerabilities a session
needs, and remove them afterwards without rebuilding.

They also want a **Kali attacker box** added to the lab network, not domain-joined.

## Goals

- New hardened base labs derived from the GOAD family: `GOAD-Base`, `GOAD-Light-Base`,
  `GOAD-Mini-Base`. Same domains, trusts, hosts and benign users/groups as the originals,
  but no vulnerabilities and a hardened configuration.
- A new **scenario** mechanism, separate from extensions, where each vulnerability is a
  self-contained unit that can be enabled and disabled on a running instance.
- Scenarios declare prerequisites. A scenario whose prerequisites the instance does not meet
  must not be selectable (hidden from the list and refused by the enable command).
- A `kali` extension for Vagrant providers (VirtualBox, VMware).

## Non-goals

- Changing the existing labs (`GOAD`, `GOAD-Light`, `GOAD-Mini`, `NHA`, `DRACARYS`, `SCCM`,
  `MINILAB`) or existing extensions. They stay byte-identical so upstream merges stay clean.
- Kali on Proxmox, AWS, Azure or Ludus (Vagrant only for now).
- Scenarios for NHA / DRACARYS / SCCM / MINILAB.
- Preserving the GOAD storyline names inside scenarios (scenarios may reuse them by choice).

## Anti-goals (would be a failure even if it "works")

- A disabled scenario leaves residue on the lab (orphan users, flipped settings, installed
  features). Disable must return the lab to the base state for everything the scenario owned.
- Two enabled scenarios silently overwriting each other's changes.
- A user able to pick a scenario the lab cannot support and only discovering it mid-playbook.
- The base lab carrying any misconfiguration-based vulnerability without a scenario enabled.
  (Known credentials are not a vulnerability here: the researcher knows them by design.)

## Constraints found in the codebase

- `Extension` (`goad/extension.py`) gates availability only by lab name (`compatibility`).
- `Extension.get_playbook(install=False)` returns `uninstall.yml`, but no command calls it
  and no extension ships one.
- Extensions merge config with `lab | combine(lab_extension, recursive=True)`, which replaces
  lists. Existing extensions only add new keys, so this is fine for them, but it is unsuitable
  for stacking vulnerabilities. Scenarios therefore do **not** merge into `lab`.
- `LabInstance.save_json_instance()` persists instance state to `workspace/<id>/instance.json`.
- `AnsibleProvisioner.run_extension()` builds the inventory list (lab + provider + global +
  enabled extension inventories) and runs a playbook from the extension's `ansible/` folder.
  Scenarios reuse this path.
- `ansible/adcs.yml` defaults `ca_web_enrollment` to `true`.
- GOAD has two CAs (`dc01` for sevenkingdoms.local, `srv03` for essos.local) and two mssql
  servers (`srv02`, `srv03`); GOAD-Light has one CA (`dc01`) and one mssql (`srv02`);
  GOAD-Mini has one CA (`dc01`) and no mssql.
- IPs already used by extensions: `.21 .31 .32 .50 .51 .52`.

## Approaches considered

1. **Native in the `goad` CLI (chosen).** New `Scenario` model + resolver in Python, state in
   `instance.json`, new CLI commands, playbooks run through the existing provisioner. The CLI
   can hide unavailable scenarios and refuse bad combinations before anything runs.
2. **Pure Ansible.** A master playbook reads an enabled list and enforces rules with `assert`.
   No Python changes, but the CLI cannot hide unavailable scenarios; failures surface
   mid-run. Violates the prerequisite requirement. Rejected.
3. **Reuse `Extension` with a `type: scenario` field.** Smallest diff, but mixes
   infrastructure and vulnerabilities in one list and one merge path, which the user ruled out.
   Rejected.

## Decisions made with the user

- Separate mechanism for vulnerabilities ("scenarios"); extensions untouched.
- Prerequisite model: **capability tags + scenario dependencies + conflicts**.
- New `-Base` labs instead of modifying existing templates.
- **Scenarios own their objects**: a scenario creates the users/SPNs/templates/ACEs it needs
  and its uninstall deletes them.
- Settings on existing infrastructure (e.g. ESC8 web enrollment, ESC6/10/11 CA flags, LLMNR)
  are handled as **setting scenarios** that revert to the declared base default.
- Base is **hardened**, not stock Windows defaults.
- Kali: **Vagrant only**.
- Build order: engine + Kali → GOAD-Base + ~5 sample scenarios → port the rest.

## Design

### 1. Base labs

Folders: `ad/GOAD-Base`, `ad/GOAD-Light-Base`, `ad/GOAD-Mini-Base`, each copied from its
original and then:

- `data/config.json`
  - Removed: every host `vulns` / `vulns_vars` / `scripts`; all `acls`; SPNs on users;
    AS-REP (`DONT_REQ_PREAUTH`) flags; passwords in descriptions; delegation settings; mssql links,
    impersonation and sysadmin grants beyond the service owner; `gmsa` readers beyond admins.
  - Kept: domains, trusts, OUs, groups, benign users, hosts, mssql install itself, CA install.
  - **Uniform password `Aa1234567890!`** for every domain account: all users, every
    `domain_password` (domain Administrator), service accounts, and the passwords in
    `data/inventory_disable_vagrant`. *Claude's call:* `local_admin_password` on every host
    uses the same value.
  - Added `lab.capabilities`: a map of capability tag to the hosts providing it, e.g.
    ```json
    "capabilities": {
      "adcs":          ["dc01", "srv03"],
      "mssql":         ["srv02", "srv03"],
      "child_domain":  ["dc02"],
      "forest_trust":  ["dc01", "dc03"],
      "member_server": ["srv02", "srv03"],
      "laps":          ["srv02", "srv03"]
    }
    ```
  - Added `lab.base_settings`: the declared hardened default for every key a setting
    scenario may touch (see §3). Uninstall of a setting scenario writes this value back.
- `data/inventory`: `[adcs_customtemplates]` emptied; `ca_web_enrollment` forced `false`
  for every domain.
- Hardened baseline applied at build time by a new `ansible/hardening.yml` (added to the
  `-Base` entries in `playbooks.yml` in place of `security.yml` + `vulnerabilities.yml`):
  - LLMNR off, NBT-NS off, mDNS off
  - SMB signing required on all hosts (client + server)
  - LDAP signing required, LDAP channel binding = always
  - Kerberos: AES only, RC4 disabled
  - NTLM: `LmCompatibilityLevel = 5`
  - LAPS enabled on members
  - Firewall on, Defender on (real-time + cloud off to avoid sample upload)
  - `StrongCertificateBindingEnforcement = 2`, `CertificateMappingMethods` default
  - CA: no web enrollment, `EDITF_ATTRIBUTESUBJECTALTNAME2` off,
    `IF_ENFORCEENCRYPTICERTREQUEST` on, only default templates published
  - Print Spooler off on DCs
- **Vagrant user disabled.** After the lab playbooks finish, `goad` runs
  `disable_vagrant.yml` automatically for `-Base` labs. From then on, all provisioning
  (scenarios, extensions on domain hosts) uses `inventory_disable_vagrant`
  (`administrator@<domain>` / `Aa1234567890!`). *Claude's call:* `provision_lab` /
  `provision_lab_from` on a `-Base` instance runs `enable_vagrant` first and
  `disable_vagrant` again at the end, because the lab playbooks expect the vagrant inventory.
- `playbooks.yml`: new `GOAD-Base`, `GOAD-Light-Base`, `GOAD-Mini-Base` entries. Same
  sequence as the originals minus `ad-acl.yml`, `security.yml`, `vulnerabilities.yml`,
  `adcs.yml` custom-template play; plus `hardening.yml` last.
- `providers/`: copied from the originals unchanged (Vagrant `Vagrantfile`s must render
  `{{lab_name}}` so VM names differ from the original lab).

### 2. Scenario package layout

```
scenarios/<name>/
  scenario.json
  ansible/
    install.yml
    uninstall.yml
    ansible.cfg        (optional, same as extensions)
  data/vars.yml        (scenario-local vars; never merged into `lab`)
  README.md            (attack walkthrough + how to verify)
```

`scenario.json`:

```json
{
  "name": "esc8",
  "description": "ADCS web enrollment over HTTP with NTLM, no EPA",
  "type": "setting",
  "requires": ["adcs"],
  "target": "adcs",
  "depends": [],
  "conflicts": [],
  "touches": ["adcs.web_enrollment"],
  "labs": ["*"]
}
```

| Field       | Meaning |
|-------------|---------|
| `type`      | `object` (creates and deletes its own AD/host objects) or `setting` (flips declared keys) |
| `requires`  | capability tags that must all be present in `lab.capabilities` |
| `target`    | capability whose hosts are the install target; empty = domain-wide via the domain's DC |
| `depends`   | scenarios that must already be enabled |
| `conflicts` | scenarios that must not be enabled |
| `touches`   | `base_settings` keys this scenario changes; overlap with an enabled scenario is an automatic conflict |
| `labs`      | optional lab-name allowlist, `*` = any lab with the capabilities |

### 3. Setting scenarios and `base_settings`

`base_settings` in each `-Base` `config.json` maps a dotted key to its hardened value per
host or domain, e.g. `"adcs.web_enrollment": false`, `"net.llmnr": "disabled"`,
`"smb.signing": "required"`. Each setting scenario:

- install: sets its `touches` keys to the vulnerable value on the target;
- uninstall: re-applies the `base_settings` value for exactly those keys on the target.

No snapshot of prior state is needed because the base is ours and declares every default.

### 4. Target selection *(builder-check calls, made by Claude)*

`enable_scenario <name> [host]`.

- Capability `target`: the user may name any host listed for that capability; otherwise the
  first listed host is used.
- Empty `target` (domain-wide): the user may name any DC; otherwise the root domain's DC
  (`dc01`) is used. The scenario applies to that DC's domain only.
- The same scenario may be enabled more than once on different targets (e.g. `esc8` on
  `dc01` and `srv03`). Scenario identity is `name@target`; `disable_scenario <name> [host]`
  needs the host only when the name is enabled on several targets.
- `touches` overlap is evaluated **per target host**: two scenarios conflict only when they
  touch the same key on the same host.
- `base_settings` is therefore keyed `host -> {key: value}` (domain-wide keys live under the
  domain's DC).

### 5. Engine (`goad/scenario.py`, `goad/scenario_resolver.py`)

- `Scenario` model mirrors `Extension`: loads `scenario.json`, exposes playbook paths.
- `Scenarios` registry loads every folder under `scenarios/`.
- Resolver, given the instance's lab capabilities and enabled scenarios:
  - `available(name)` → ok / reasons (missing capability, missing dependency, explicit
    conflict, `touches` overlap, lab not in `labs`).
  - `install_order(names)` → topological order over `depends`; error on cycles.
  - `disable_check(name)` → list of enabled dependents.
- `GoadPath` gains `get_scenarios_path()` / `get_scenario_path(name)` / ansible path.

### 6. Instance state

`instance.json` gains:

```json
"scenarios": [
  { "name": "esc8", "target": "srv03", "enabled_at": "2026-11-17T10:00:00Z" }
]
```

Old instances without the key load as `[]`. Scenarios are only allowed on instances whose
lab declares `capabilities` (i.e. `-Base` labs); other labs show "no scenarios available".

State is written **after** a successful install and **removed after** a successful
uninstall. A failed install triggers that scenario's `uninstall.yml` as best-effort cleanup
and leaves state unchanged; the failure is reported.

*Builder-check calls, made by Claude:*

- **Failed uninstall:** the entry stays in state with `"status": "dirty"`. A dirty scenario
  still counts for conflicts, `touches` overlap and dependencies, and can be retried with
  `disable_scenario`. A failure inside `--cascade` or `reset_scenarios` stops the run at that
  scenario.
- **Re-provisioning the base** (`provision_lab`, `provision_lab_from`): after the lab
  playbooks finish, every enabled scenario's `install.yml` is re-run in dependency order, so
  `hardening.yml` cannot silently revert setting scenarios while state says they are on.
- Copied `-Base` Vagrantfiles are edited to use `{{lab_name}}` in VM names (the originals
  hardcode e.g. `GOAD-Mini-DC01`).

### 7. CLI

New commands in `goad.py` (interactive menu + `-t` task where applicable):

- `list_scenarios` — enabled scenarios first, then available ones; unavailable ones hidden by
  default, `list_scenarios all` shows them with the reason.
- `enable_scenario <name> [host]` — validate via resolver, refuse with reasons, else run
  `install.yml`, record state.
- `disable_scenario <name> [--cascade]` — refuse if dependents are enabled unless
  `--cascade`, which disables dependents first in reverse topological order.
- `reset_scenarios` — disable everything in reverse order.

Menu (`goad/menu.py`) gets a "scenarios" block shown when an instance is loaded.

### 8. Provisioning

`AnsibleProvisioner.run_scenario(scenario, target, install=True)`:
inventory = `inventory_disable_vagrant` + provider + global + enabled extension inventories;
extra vars: `scenario_target=<host>`, `scenario_name=<name>`, `data_path` of the lab. The
scenario playbook loads `ansible/data.yml` for `lab`, then its own `data/vars.yml`.
Playbooks must be idempotent; install and uninstall each run cleanly twice.

### 9. Kali extension (`extensions/kali/`)

- `extension.json`: `compatibility: ["*"]`, machine `kali`, impact "adds a non-domain Kali".
- `providers/virtualbox/Vagrantfile`, `providers/vmware/Vagrantfile`: box
  `kalilinux/rolling`, IP `{{ip_range}}.99`, 2 CPU, 4096 MB, ssh forwarded port 2299.
- `inventory`: `kali ansible_host={{ip_range}}.99 ansible_connection=ssh`, in group
  `[extensions]` only (not `domain`, not `linux_domain`).
- `ansible/install.yml`: set `/etc/resolv.conf` (via systemd-resolved / NetworkManager) to
  the lab DCs first, then upstream; add `/etc/hosts` entries for every lab host FQDN; install
  `kali-linux-default` if missing. No domain join, no Kerberos realm config beyond
  `/etc/krb5.conf` with the lab realms (so `impacket -k` works).
- Kali keeps its own `vagrant` SSH user. It is not in `domain`/`linux_domain`, so
  `disable_vagrant.yml` never touches it.
- `ansible/uninstall.yml`: none needed (destroying the VM is the uninstall).

### 10. Initial scenario set (phase 2)

| Name | Type | Requires | Owns / touches |
|------|------|----------|----------------|
| `kerberoast` | object | — (domain-wide) | user `svc_kerb` with SPN |
| `asrep-roast` | object | — | user `asrep_user` with `DONT_REQ_PREAUTH` |
| `esc1` | object | `adcs` | template `ESC1-Vuln` (enrollee supplies subject, Domain Users enroll) |
| `esc8` | setting | `adcs` | `adcs.web_enrollment` |
| `llmnr` | setting | — | `net.llmnr`, `net.nbtns` |

Scenario-owned accounts also use `Aa1234567890!`; the researcher adds it to the wordlist
when cracking. No initial-access (`foothold`) scenario is needed.

Phase 3 ports the remaining GOAD vulnerabilities following the same two patterns, plus
setting scenarios for each hardened item (SMB signing, LDAP signing/binding, RC4,
Defender, firewall, spooler).

## Left to the builder

- Exact PowerShell/registry used per hardening item and per scenario.
- Whether `hardening.yml` is one role or several.
- Wording of CLI output and README walkthroughs.
- Test harness shape (unit tests for the resolver are expected; playbooks verified on a live
  GOAD-Mini-Base instance).
