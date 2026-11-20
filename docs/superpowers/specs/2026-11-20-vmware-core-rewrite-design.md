# VMware-native core rewrite — design

## Intent

GOAD becomes a tool that deploys and maintains one live Active Directory lab on VMware Workstation,
built with Packer and configured with Ansible. The problem it solves is maintenance: a lab is several
VMs that only make sense together, so they must be managed as one unit, and the lab must always be able
to return to a clean, known-good state after components are added or configuration is tweaked, without
a redeploy.

The current code (`main`) has most of the pieces (named whole-lab snapshots, scenarios, extensions), but
it is built as a multi-provider tool on top of Vagrant. That costs VMware features, speed (a lab
snapshot takes 30+ minutes), and reliability (`ruby.exe` locks, the vagrant account gate, the
vagrant-vmware-utility VMnet failure). The interface does not expose everything the tool can do, and
the console needs piped `yes y` to script.

This work is a rewrite from scratch on a new trunk branch, `vmware`, which replaces `main` as the
branch all further work starts from.

## Goals

- One lab at a time, managed as one unit: deploy, start, stop, snapshot, reset, destroy act on every VM.
- A protected `base` snapshot taken automatically at the end of a successful deploy. `goad lab reset`
  with no argument returns to it.
- Fast whole-lab snapshots: powered off, all VMs in parallel.
- Fast deploys: linked clones from Packer templates that already carry updates and Windows features;
  provisioning only configures.
- A command-line interface where every capability is one shell command, scriptable, no piped answers.
- Versioned, reproducible VM templates: Windows Server 2022, Windows Server 2025, Windows 11,
  Ubuntu 24.04.
- The three `-Base` lab topologies (`GOAD-Base`, `GOAD-Light-Base`, `GOAD-Mini-Base`) as the shipped
  labs: hardened, uniform password, no intentional weakness.

## Non-goals

- Any provider other than VMware Workstation on a Windows host (no ESXi, VirtualBox, Proxmox, Ludus,
  AWS, Azure).
- Vagrant, in any role.
- More than one lab deployed at a time.
- Migrating labs built by the old code. They are destroyed and redeployed on the new branch.
- Scenarios and extensions in the first release. They return later, one at a time, each ported onto the
  new core and tested on 2022/2025 (separate designs).
- Labs other than the three `-Base` ones in the first release (GOAD, NHA, SCCM, DRACARYS, MINILAB stay on
  `main`).
- A full-screen terminal UI or web UI. A terminal dashboard may come later on top of the same core.
- Memory (live) snapshots.

## Anti-goals

- A reset that leaves the lab in a state goad's record does not match.
- A command that blocks a scripted run waiting for input.
- A template change that silently breaks a deployed lab (linked clones depend on their template).
- A core that grows features before the base deploy/reset loop is fast and reliable.

## Constraints

- Host: Windows with VMware Workstation 17.5+. goad and Ansible run in WSL2 (NAT networking mode; mirrored
  mode hides the VMware host-only adapters). goad calls Windows binaries (`vmrun.exe`, `packer.exe`,
  `vmware-vdiskmanager.exe`) through WSL interop.
- Lab network: a host-only VMnet (default `VMnet2`, `192.168.56.0/24`) created once by the user;
  `vagrant-vmware-utility` could not create it. goad checks it exists and tells the user how to create it
  if not; it does not create it (needs admin).
- Corporate TLS interception (Cato Networks) on the user's network: VMs must trust an extra root CA for
  anything they download. Templates import every certificate in a configured folder into the machine
  root store.
- Windows evaluation licences (180 days servers, 90 days Win11). A rebuild from templates is the renewal
  path.
- Windows 11 requires TPM 2.0 and Secure Boot. Workstation's vTPM requires VM encryption, and encrypted
  VMs cannot be linked-cloned. The Win11 template bypasses the checks in its unattend
  (`HKLM\SYSTEM\Setup\LabConfig\BypassTPMCheck`, `BypassSecureBootCheck`) and has no vTPM.
- Server 2025 ships harder defaults than 2022: LDAP signing and channel binding, SMB signing required,
  NTLMv1 removed, RC4 Kerberos restricted. The hardened base keeps them. Each future scenario must open
  exactly what it needs and be tested on 2025.

## Approaches

Three decisions shaped this design. The user chose each.

**VM build and lifecycle**
- *A. Drop Vagrant: Packer templates + `vmrun` linked clones + Ansible (chosen).* One toolchain talks to
  VMware. A clean base is literal: the template snapshot, then the lab `base` snapshot. Costs: goad owns
  template builds and clone/first-boot code; VMnet creation stays a manual one-time step.
- *B. Keep Vagrant to build only.* Less new code, but every Vagrant pain stays in the build path.

**Snapshot type**
- *Powered off (chosen).* goad shuts the lab down, snapshots every VM in parallel in seconds, boots.
  Reset is revert + boot (a few minutes until the DCs answer). Clocks are fresh; AD replication state is
  consistent across DCs.
- *With memory.* Instant resume, but several GB written per VM (the 30+ minute cause today) and stale
  guest clocks after a revert.

**Scope of the rewrite**
- *Everything, minimal first (chosen).* New Python core, new lean Ansible roles, the three `-Base`
  topologies, zero scenarios and extensions at first.
- *Tool only.* New core, existing roles and scenarios ported. Faster to feature parity, but keeps the slow
  provisioning and untested-on-2025 scenarios.
- *Tool + Ansible.* Middle ground; scenarios ported right after.

**Interface**
- *Command-line subcommands (chosen).* Every action is a shell command; prompts only on a TTY; `--yes`
  skips them.
- *Full-screen terminal UI.* Good for watching runs, hard to script.
- *Local web UI.* Most polished, most code to maintain.

## Design

### Repository on the `vmware` branch

The old code is deleted on the branch, not kept beside the new: no `goad/provider/*` other than VMware,
no `template/provider`, no `vagrant/`, no `packer/proxmox`, no `ad/` labs other than the three `-Base`
ones, no `scenarios/` or `extensions/` until ported. `main` keeps the old tool.

Python stays the language (Ansible is Python; goad already is).

### Templates

- Built by Packer (`vmware-iso` builder, run as `packer.exe` on the Windows host) from ISOs, one template
  per OS: `win2022`, `win2025`, `win11`, `ubuntu2404`.
- Each build is versioned (`win2025-v3`) and immutable once built. Its folder holds the VM and a `base`
  snapshot taken powered off.
- Windows templates carry: latest cumulative update at build time, VMware Tools, WinRM/PSRP enabled,
  the AD DS, DNS, AD CS and RSAT features installed but not configured (servers only), the extra root CAs,
  and are sysprepped (generalized) so every clone gets a unique SID and runs specialize at first boot.
- The Ubuntu template uses cloud-init with the VMware guestinfo datasource.
- `goad template build <os>` builds one; `goad template list` shows versions and which lab uses which.
  Deleting a template a deployed lab uses is refused.
- `goad template test <os>` proves a template deployable: linked clone, first boot with guestinfo,
  readiness check (PSRP or SSH), destroy. No `-Base` lab uses `win11` or `ubuntu2404` yet; this command is
  how the first release proves them. *(Builder's call.)*
- ISO source: per-OS entry in goad's config with a local path or URL and a checksum. Microsoft evaluation
  ISO URLs are the defaults where stable.

### Lab definition

One declarative file per lab (`labs/<lab>/lab.yml`) replaces `config.json`, the inventory and the
Vagrantfile. It lists:

- hosts: short name, hostname, template OS, CPU, RAM, last IP octet, role (`dc`, `server`, `workstation`,
  `linux`), domain;
- domains, forests, trusts, OUs, users, groups, ACLs, local groups and the security settings the `-Base`
  labs have today;
- lab-wide values: domain admin password (`Aa1234567890!`, uniform as today), DNS forwarder.

Default OS mapping for the shipped labs: DCs on 2025, member servers on 2022, so both versions are
exercised. The Ansible inventory is generated from this file.

Domain and forest functional level is 2016 (`WinThreshold`), so 2022 and 2025 DCs can mix and later
extensions can add a 2022 DC. *(Builder's call, accepted.)*

LAPS is native Windows LAPS (not the legacy MSI, which is blocked on Server 2025 and recent Windows 11 and
needs a download). The `-Base` `use_laps` hosts get the Windows LAPS policy; `goad creds` reads their
rotated local Administrator password with `Get-LapsADPassword`. Every other account keeps the uniform
password. *(Builder's call.)*

**Working copy.** Deploy copies the shipped `labs/<lab>/lab.yml` into the state folder
(`~/.goad/lab.yml`). The user tweaks that copy and runs `goad lab provision`. The shipped file in the repo
is never modified by goad. *(User decision.)*

### Deploy

`goad lab deploy <lab> [--range 192.168.56]` refuses if a lab is already deployed. Steps, each recorded
in the state file so a re-run resumes from the failed step:

1. Check: Workstation, `vmrun.exe`, `packer.exe`, the VMnet, the required templates, disk space.
2. Clone: `vmrun clone <template.vmx> <lab vm.vmx> linked -snapshot=base -cloneName=<lab>-<host>`, in
   parallel.
3. Configure the `.vmx`: `memsize`, `numvcpus`, NIC 1 NAT (internet), NIC 2 on the lab VMnet, and
   `guestinfo.goad.*` keys (hostname, IP, mask, DNS, admin password).
4. First boot: the template's specialize/first-logon script reads `guestinfo.goad.*` through VMware Tools,
   sets the hostname, the static IP on the lab NIC and the local Administrator password, then reboots.
   goad waits until every host answers PSRP (Windows) or SSH (Linux) on its lab IP.
5. Provision: Ansible against the generated inventory.
6. Finish: remove the template's setup account, shut down, take the protected `base` snapshot, boot.

### Provisioning (Ansible)

New, lean roles written for the `-Base` topologies only. Speed rules:

- connection `psrp` for Windows, forks = host count;
- one play per domain level so independent domains run in parallel (forest root DCs, then child DCs,
  then members);
- no fixed waits; reboot only where AD requires it, with `win_reboot` and readiness checks;
- features come from the template, so roles configure only;
- every role is idempotent: `goad lab provision` can re-run on a live lab.

Ansible connects with the lab's own credentials (local Administrator before domain join, domain
Administrator after). There is no permanent setup account, so there is no vagrant-style gate.

Every deploy and provision logs duration per step and per role, so slow steps stay visible.

### Snapshots and reset

- Always whole-lab, always powered off: graceful guest shutdown of every VM in parallel, hard power-off
  after a timeout, `vmrun snapshot` on every VM in parallel, boot.
- `base` is taken by deploy and is protected: `goad snapshot delete base` is refused.
- `goad snapshot take [label]` adds a checkpoint. goad records each snapshot (name, time, label) in the
  state file, plus a copy of the working `lab.yml` as it was at that moment.
- `goad lab reset [snapshot]` (default `base`): power off, `vmrun revertToSnapshot` on every VM in
  parallel, restore the snapshot's copy of the working `lab.yml`, boot, wait for readiness. Later
  snapshots are kept. VMs and config always match after a reset. *(User decision.)*
- A snapshot that is missing on any VM is reported and cannot be reset to.

### State

One state file (`~/.goad/lab.json`): lab name, IP range, host to `.vmx` map, templates used (with
versions), deploy step reached, snapshots (each with its `lab.yml` copy). The working `lab.yml` sits
beside it. VM files live under a configured Windows folder
(`C:\goad\lab\<host>\`); templates under `C:\goad\templates\<os>-v<n>\`.

### CLI

```
goad template build win2025|win2022|win11|ubuntu2404
goad template test win2025|win2022|win11|ubuntu2404
goad template list
goad template delete <name>

goad lab deploy <lab> [--range 192.168.56]
goad lab status                    # per-VM power, IP, template, current snapshot
goad lab start | stop
goad lab provision [--tags ...]
goad lab reset [snapshot]          # default: base
goad lab destroy

goad snapshot take [label]
goad snapshot list
goad snapshot delete <name>

goad creds
goad vm start | stop | console <vm>
goad check
```

- Prompts appear only on a TTY; `--yes` answers them. Non-TTY without `--yes` fails with a clear message
  instead of waiting.
- Output: tables for lists, one progress line per VM for parallel steps, a duration summary at the end.
- Exit codes: 0 success, non-zero failure, so scripts can chain commands.

### Release gate

The core is done, and scenario/extension porting may start, when on the user's machine with
`GOAD-Light-Base` *(user decision)*:

- a whole-lab snapshot takes under 2 minutes;
- a reset to `base` takes under 5 minutes until every host answers;
- a deploy from already-built templates takes under 30 minutes;
- 3 deploys in a row and 5 resets in a row succeed with no manual fix.

`goad template test` passes for all four templates.

## Left to the builder

- Python packaging, CLI library, module layout, and test framework.
- Packer template layout, unattend/autounattend content, and update installation method.
- The exact `guestinfo` key names and the first-boot script.
- Ansible role boundaries and variable names, within the speed rules above.
- Timeouts and readiness checks.
- How the `-Base` `config.json` content maps into `lab.yml`.
