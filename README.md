# goad-v2

goad deploys and maintains **one Active Directory lab on VMware Workstation**. Packer builds the VM
templates, goad clones them, and Ansible configures the lab. The lab is managed as one unit: it
deploys, snapshots, resets and is destroyed as a whole. You can always reset it to a clean base after
adding components or tweaking configuration, without redeploying.

> [!CAUTION]
> Lab VMs are meant for security practice. Do not expose them to the internet.

This branch (`goad-v2`) is a rewrite. The original multi-provider GOAD lives on `main`.

## Status

| Part | State |
|------|-------|
| Host checks, VM templates (`goad check`, `goad template ...`) | available |
| Labs `1domain` (dc01 kingslanding, srv02 castelblack), `2domains`, `2forests` (`goad lab ...`, `goad snapshot ...`) | available |
| Release gate (2domains) | accepted 2026-11-23 with one deploy 40 s over the limit, see docs/release-gate/ |
| Scenarios (52, one YAML file each in `scenarios/`) | available |
| Extensions | available |

## Host requirements

- Windows with VMware Workstation 17.6 or later (26.x tested).
- WSL2 in **NAT** networking mode (mirrored mode hides the VMware host-only adapters).
- Packer 1.11 or later on Windows (`winget install Hashicorp.Packer`). goad finds `packer.exe` on PATH
  or in the winget package folder.
- A host-only network `VMnet2` with subnet `192.168.56.0/24`. Create it once in Virtual Network Editor
  (it needs admin); goad checks it but never creates it.
- About 100 GB free on the drive that holds the templates.

## Install

```bash
python3 -m venv ~/.goad/v2
~/.goad/v2/bin/pip install -e .
~/.goad/v2/bin/ansible-galaxy collection install -r ansible/requirements.yml
~/.goad/v2/bin/goad check
```

## Configuration

Optional: `~/.goad/config.yml`. Every key has a default:

```yaml
template_root: C:\goad\templates     # versioned templates
lab_root: C:\goad\lab                # lab VMs
vmware_dir: C:\Program Files (x86)\VMware\VMware Workstation
packer: packer.exe                   # or a full path
vmnet: VMnet2
ip_range: 192.168.56
ca_certs_dir: C:\goad\certs          # see below; unset by default
isos:                                # override an ISO source per OS
  win2025:
    url: D:\iso\win2025.iso
    checksum: none                   # or sha256:<hex>
```

Default ISOs are the Microsoft evaluation images (Server 2022, Server 2025, Windows 11 Enterprise) and
Ubuntu 24.04 live server.

### Networks with TLS interception

If your network intercepts TLS (a corporate proxy with its own root CA), export that root certificate
into a folder and set `ca_certs_dir`. Every `.cer` / `.crt` file in it is trusted by every template.

## Templates

```bash
goad template build win2025      # win2022 | win2025 | win11 | ubuntu2404
goad template list
goad template test win2025       # clone, first boot, readiness check, delete
goad template delete win2025-v1  # --yes to skip the prompt
```

- Each build is a new version (`win2025-v1`, `win2025-v2`, ...) under `template_root`. It is immutable,
  and it ends on a powered-off snapshot named `base`.
- Windows templates are patched, have VMware Tools, PSRP enabled, and are sysprepped. Server templates
  also have AD DS, DNS and the RSAT tools (AD, DNS, AD CS) installed but not configured. The AD CS role
  itself is installed by provisioning, on CA hosts only.
- Windows 11 is installed without the TPM / Secure Boot checks and without a vTPM, so it can be
  linked-cloned.
- A template that the deployed lab uses cannot be deleted.
- Build logs go to `~/.goad/logs/`.

## Labs

```bash
goad lab deploy 2domains         # 1domain | 2domains | 2forests; --range 192.168.57 to move the network
goad lab status
goad snapshot take pre-adcs      # briefly powers the lab off
goad snapshot list
goad lab reset [snapshot]        # default: base
goad lab destroy                 # --yes to skip the prompt
goad creds
goad vm stop dc01                # also: vm start, vm console; --hard on stop
```

- `deploy` clones the templates, configures network and hostnames, and boots every VM. It is resumable:
  run it again after a failure and it continues at the failed step. It prints a duration table at the end.
- The working copy of the lab definition is `~/.goad/lab.yml`. `lab.json` next to it records the deploy
  state.
- A snapshot covers every VM and a copy of `lab.yml`. `base` is taken at the end of deploy and cannot
  be deleted. `lab reset` reverts all VMs and restores `lab.yml` from the snapshot; later snapshots are kept.
- `lab start` and `lab stop` act on the whole lab. `lab provision [--tags a,b]` runs `ansible/site.yml`
  and fails if it does not exist yet.
- `lab destroy` deletes the VMs, their folders and the state.

Example:

```bash
goad lab deploy 1domain
goad snapshot take before-change
goad lab reset before-change     # prints: lab reset to before-change in 94s
goad lab destroy --yes
```

## Scenarios

A scenario is one vulnerability or misconfiguration (kerberoast, ESC8, rbcd, ...) described by one YAML
file in `scenarios/`. You turn them on and off on a running lab.

```bash
goad scenario list                                  # name, kind, description, valid targets, where enabled
goad scenario enable kerberoast                     # --target dc01 to pick a host; default: first valid target
goad scenario disable kerberoast --target dc01      # --target needed if enabled on several hosts; --yes skips the prompt
```

- The list of enabled scenarios lives in the `scenarios:` key of `~/.goad/lab.yml`, as mappings, e.g. `scenarios: [{name: kerberoast, target: dc01}]`. `goad snapshot list` shows them as `name@target`.
- `enable` appends the entry to the working `lab.yml` and provisions with tags `content,local_groups,settings`.
  It takes no snapshot. Run `goad snapshot take [label]` first if you want a fixed point to return to.
  If provisioning fails, the entry stays; run `goad lab provision` again or disable the scenario.
- `disable` removes the entry, resets the lab to the newest snapshot whose content is contained in the new
  `lab.yml`, then replays the remaining scenarios. It refuses, before touching any VM, if you deleted lab
  content from `lab.yml` since `base`.
- A snapshot's `lab.yml` is expanded with the current scenario files, so editing a scenario file can change
  which snapshot `disable` picks.
- `goad snapshot list` has a Scenarios column. `goad creds` also lists scenario users.
- Five scenarios wait for extensions and are not in `scenarios/` yet: `mssql-impersonate-login`, `mssql-impersonate-user`, `mssql-linked`, `mssql-sysadmin`, `iis-upload`.

## Extensions

An extension adds VMs and services to a lab (one YAML file each in `extensions/`). You add and remove them
on a running lab.

```bash
goad extension list                  # name, description, applies to this lab, installed
goad extension add elk               # add to lab.yml, create the VMs, provision, snapshot ext-elk
goad extension remove elk            # --yes skips the prompt
```

- The installed list lives in the `extensions:` key of `~/.goad/lab.yml`. `goad creds` lists extension accounts; `goad snapshot list` has an Extensions column.
- A snapshot taken with a different extension list than the current `lab.yml` is unusable: `goad lab reset` refuses it, and `goad snapshot list` marks it `(unusable)`.
- `add` is resumable: if it fails, run the same command again. Another extension cannot be added while one is half added.
- `remove` works newest first: remove the last extension added before an older one. It refuses while scenarios depend on the extension, deletes only the VMs it brought, resets to the newest snapshot without it and replays the remaining scenarios.

## Provisioning

`deploy` runs `ansible/site.yml` as its `provision` step. `goad lab provision` runs it again on the
deployed lab. Plays run in this order:

| Play | Hosts | Tags | Roles |
|---|---|---|---|
| common | all Windows hosts | `common` | connect (members, runs with every tag), common |
| forest | forest root DCs | `forest` | forest |
| child | child DCs | `child` | child_domain |
| trust | DCs | `trust` | dc_dns records cleanup, trust |
| join and content | DCs and members | `join`, `content`, `adcs` | join (members), ca_feature (starts the AD CS role install on CA hosts), ad_content (DCs) |
| foreign members | DCs | `content` | foreign_members (cross-forest group members) |
| post-join | all Windows hosts | `laps`, `local_groups` | laps_schema, laps_dc, local_groups, laps_host |
| settings | all Windows hosts | `settings`, `adcs` | adcs (CA hosts: waits for the AD CS role install, then the CA), settings (the lab.yml `settings` catalogue) |

```bash
goad lab provision                       # every play
goad lab provision --tags content        # OUs, users, groups and foreign members (and the join play)
goad lab provision --tags settings       # re-apply security settings after editing lab.yml
goad lab provision --tags laps,adcs      # a tag selects whole plays; the connect role always runs
```

- Provisioning is additive: edit `~/.goad/lab.yml` (users, groups, settings) and run `goad lab provision`.
  Removing a user or group from `lab.yml` does not delete it from AD: `goad lab reset` is the way back
  to a clean state. Adding, removing or renaming hosts, or changing their OS or address, needs a
  destroy and redeploy.
- A second run on an unchanged lab reports `changed=0` on every host.
- Each run writes `~/.goad/logs/provision-<date>.log`. It ends with the `PLAY RECAP` and a per-role
  duration table (the `profile_roles` callback), for example `forest ---- 1280.16s` on a fresh 2forests deploy.
- Hosts with `laps: true` get native Windows LAPS. `goad creds` reads the current password from the
  domain controller with `Get-LapsADPassword` and shows it in the `local <host> (LAPS)` row. When the
  DC cannot be reached, the row says `unavailable: ...`.

## Commands and scripts

Every command works without a terminal. A prompt that cannot be answered fails with exit code 2 and
asks for `--yes`. Errors exit 1.

## Release gate

The core counts as done when one run of the gate on `2domains` passes all four limits. Each limit is
strict: a sample equal to the limit fails.

| Check | Limit | Count |
|---|---|---|
| Whole-lab snapshot | under 120 s | 3 |
| Reset to `base`, until every host answers | under 300 s | 5 in a row |
| Deploy from already-built templates | under 2100 s | 3 in a row |
| `goad template test` for `win2022`, `win2025`, `win11`, `ubuntu2404` | passes | 1 each |

Every command must succeed on its first call: a deploy that needs a resume fails the gate.

Run it by hand on the VMware host with all four templates built, 16 GB of free RAM and no lab
deployed:

```
pytest -m live -k gate -s
```

It takes 2 to 4 hours and writes a timed report to `~/.goad/logs/release-gate-<YYYYmmdd-HHMMSS>.md`.
Committed reports are in `docs/release-gate/`.

The 2026-11-22 run failed by one sample: the first deploy took 2140 s, the other two 1917 s and
1900 s. The maintainer accepted that result on 2026-11-23. Scenario and extension porting starts
only after an accepted gate run.

## Development

```bash
~/.goad/v2/bin/pip install -r requirements-dev.txt
~/.goad/v2/bin/pytest            # unit tests
~/.goad/v2/bin/pytest -m live    # on the VMware host: real builds and template tests
```
