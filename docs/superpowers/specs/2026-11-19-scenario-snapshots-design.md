# Scenario and extension snapshots — design

## Intent

After attacking a scenario, the user wants a lab that is guaranteed clean. `disable_scenario` runs the
uninstall playbook, which cleans what the scenario installed and the cheap attack leftovers, but cannot
promise a pristine lab (documented residue: tooling, certificates issued from built-in templates, GPO
changes made by the attacker, ...). A whole-lab snapshot taken before the scenario is applied, and
reverted instead of disabling, gives that guarantee.

## Goals

- Before `enable_scenario` applies a scenario, ask the user whether to take a whole-lab snapshot. The
  snapshot name contains the scenario.
- Before `disable_scenario` runs the uninstall, look for the scenario's snapshot. If it exists on every VM,
  print the snapshot order, mark every scenario that the revert would lose, and ask the user to revert
  instead of disabling.
- Keep goad's record (`instance.json`) consistent with the lab after a revert.
- The same for extensions: snapshot before `install_extension`, and a new `remove_extension` command that
  offers the revert (see Extensions).

## Non-goals

- Per-VM snapshots or reverts. A scenario touches the target, the DC of its domain, the CA host, and for
  `foreign-group-acl` / `sid-history` the partner forest. Reverting one DC of a multi-DC forest causes a
  USN rollback. Snapshot and revert are always whole-lab.
- Reading the hypervisor snapshot tree (`vmrun listSnapshots -showTree`). Approach B, rejected.
- Providers other than VMware Workstation via Vagrant (`vmware_desktop`). Other providers must keep
  working without the prompts (see Behaviour on other providers).
- Changing the existing `snapshot` / `reset` commands (`vagrant snapshot push` / `pop`).

## Anti-goals

- A prompt that blocks a scripted run (live harness piping commands into the console, `goad.py -t`).
- A revert that leaves `instance.json` listing scenarios the lab no longer has, or a later revert to a
  snapshot from a timeline that no longer exists.

## Approaches

- **A. goad records the order (chosen).** The snapshot name is stored on the scenario entry in
  `instance.json`; the order of entries is the snapshot order. `vagrant snapshot list` only confirms the
  snapshot still exists on every VM. Picked because `instance.json` already holds order and targets, and
  Vagrant lists snapshots without parent order.
- **B. hypervisor tree.** `vmrun listSnapshots <vmx> -showTree` per VM. Sees snapshots taken outside goad,
  but VMware-only, bypasses Vagrant, and cannot map a snapshot to a scenario state.

## Design

### Snapshot record

`instance.json` gets an ordered `snapshots` list (oldest first). Each record captures goad's view of the
lab at the moment the snapshot was taken, so a revert can restore that view exactly, whatever happened in
between (uninstalls, `reset_scenarios`, `--cascade`, dirty retries, `enable_vagrant` / `disable_vagrant`,
extensions):

- `name`: the snapshot name.
- `for`: what the snapshot was taken for: a scenario entry key (`esc4@dc01`) or an extension
  (`extension:ws01`).
- `scenarios`: the enabled entries at snapshot time (name, target, status, their own snapshot name).
- `vagrant_disabled`, `extensions`: the instance fields at snapshot time.

*Builder's call (reviewer gap 1 and 2):* recording state instead of relying on entry order keeps
`instance.json` consistent after a revert even when entries were removed from the middle of the list, and
covers the vagrant account state (a revert to a snapshot taken before `disable_vagrant` brings the vagrant
account back; goad must know).

### Naming

`scn-<seq>-<scenario>@<host>`, for example `scn-03-esc4@dc01`. `<seq>` is a per-instance counter (two
digits, zero padded, grows past 99 as needed), stored in `instance.json`, advanced only when a snapshot is
taken and never reused, so names stay unique after reverts.

### Enable

1. Resolve and check the scenario as today (refusals unchanged, nothing asked on a refusal).
2. Ask: `Take a lab snapshot before enabling <scenario>@<host>? (y/N)`.
3. On `y`: `vagrant snapshot save <name>` on all VMs and append the snapshot record. On failure: delete
   any partial snapshot, log the error and stop (do not apply the scenario without the snapshot the user
   asked for).
4. On `n`: enable as today; no record.
5. Apply the scenario as today.
   - Install fails, cleanup succeeds: the entry is removed as today; goad deletes the snapshot and its
     record (it belongs to no entry).
   - Install fails, cleanup fails: the entry is marked dirty and keeps its snapshot, so the user can revert
     out of it. *Builder's call (reviewer gap 3).*

### Disable

1. Find the entry's snapshot record. If there is none, or `vagrant snapshot list` shows the snapshot
   missing on a VM that existed when it was taken (VMs of extensions in the record), disable as today and
   log why no revert is offered. VMs of extensions added after the snapshot do not have it; the revert
   destroys them (step 4).
2. Otherwise print what the revert does, from the record and the current state:

   ```
   scenario snapshots (oldest first):
     scn-01-maq@dc02     for maq@dc02
     scn-02-rbcd@srv02   for rbcd@srv02    <- revert point
     scn-04-esc4@dc01    for esc4@dc01     deleted
   revert to scn-02-rbcd@srv02:
     removed:  rbcd@srv02 (the scenario you disable)
     lost:     esc1@dc01, esc4@dc01        (enabled after the snapshot)
     restored: smb-signing-off@srv02       (disabled after the snapshot, back in the lab)
   ```

   `lost` = current entries not in the record (the chosen entry shown as `removed`); `restored` = record
   entries no longer enabled. Snapshot records after the revert point are listed as `deleted`.
   A change of `vagrant_disabled` is printed too (`vagrant account: enabled again`), and extensions
   added after the snapshot are listed as `lost` with their VMs (`ws01: GOAD-Base-WS01 destroyed`).
3. Ask: `Revert the lab to <name> instead of disabling? (y/N)`.
4. On `y`: destroy the VMs of extensions not in the record (`vagrant destroy -f <vm>`, while the
   Vagrantfile still defines them), then `vagrant snapshot restore --no-provision <name>` on the other VMs.
   On success: set the instance
   `scenarios`, `vagrant_disabled` and `extensions` to the record's values (regenerating the instance
   folder, so the Vagrantfile and inventories match); delete the revert-point
   snapshot and every snapshot after it, with their records (they belong to a timeline that no longer
   exists, and the lab is now in the revert point's state). On restore failure: log, leave `instance.json`
   unchanged, and stop.
5. On `n`: disable as today.
6. `--cascade` applies to the uninstall path only; a revert already removes everything after the revert
   point, dependents included.

When an entry leaves through the uninstall path, its own snapshot and record are deleted (the revert offer
is keyed on the entry, so nothing would offer it again). Other records are untouched: they still describe
their own moment correctly.

### Extensions

Extensions add VMs (ws01, elk, wazuh, kali, lx01, guacamole, exchange) and some push agents or domain
objects to the existing hosts. Today they have no removal path. Scenario and extension snapshots share one
ordered `snapshots` list, so a revert to either kind loses everything after it.

- **`install_extension <name>`**: before `vagrant up`, ask
  `Take a lab snapshot before installing extension <name>? (y/N)`. On `y`, snapshot all existing VMs as
  `ext-<seq>-<name>` (same counter as scenarios) and append the record (`for: extension:<name>`). Failure
  rules as for enable: a failed snapshot stops the install; a failed install keeps the snapshot so the user
  can revert out with `remove_extension`.
- **`remove_extension <name>`** (new command):
  1. With a snapshot record whose snapshot exists on every VM it covers: print the same report as a
     scenario revert (revert point, `lost` scenarios and extensions, `restored`, `deleted` snapshots) and
     ask `Revert the lab to <name> instead of removing? (y/N)`. On `y`, revert exactly as a scenario
     revert (the extension's VMs are destroyed because the record does not list it).
  2. Without a snapshot, or on `n`: *user's choice:* destroy only the extension's VMs
     (`vagrant destroy -f <vm>` before the Vagrantfile is regenerated), then `disable_extension`. Warn
     before acting: `agents and domain objects the extension pushed to the lab stay (computer accounts,
     DNS records, agents)`. Ask `Remove extension <name> without revert? (y/N)`.
  3. An extension that other enabled extensions need (none declare this today) is not special-cased.
- **`provision_extension`**: unchanged (re-runs the playbook on an installed extension, no prompt).
- An uninstall-path removal deletes the extension's own snapshot and record, like a scenario disable.
- The extension's VM names come from its provider Vagrantfile (`:name => "{{lab_name}}-WS01"`); the
  builder resolves them against the instance's generated Vagrantfile.

### Other scenario commands

- Re-provisioning (`reapply`): unchanged; entries keep their snapshot names.
- `reset_scenarios`: uninstall path, no prompts; deletes each removed entry's snapshot and record, like any uninstall.
- Dirty entries: a dirty entry with a snapshot gets the revert offer like any other entry; reverting is a
  clean way out of a failed enable or disable.
- `list_scenarios`: show the snapshot name of each enabled entry.

### Non-interactive runs

- `--no-snapshot` on `enable_scenario`, `disable_scenario`, `install_extension` and `remove_extension`
  skips the snapshot and revert prompts and behaves as without a snapshot (`remove_extension` still asks
  its removal confirmation unless `--yes` is given).
- When stdin is not a TTY, behave as `--no-snapshot` (the live harness and `goad.py -t` keep working
  unchanged).

### Behaviour on other providers

The prompts appear only when the instance provider supports named snapshots. The provider interface gets
`snapshot_save(name)`, `snapshot_restore(name)`, `snapshot_delete(name)`, `snapshot_list() -> per-VM
names`. The Vagrant provider implements them; providers without them behave as `--no-snapshot`.

## Constraints

- VMware Workstation only for live verification (user only uses VMware Vagrant).
- After provisioning the instance is `vagrant_disabled` (vagrant user disabled in the guests). Vagrant
  snapshot commands go through the hypervisor, but `restore` may wait on the guest communicator; the
  builder verifies live that `--no-provision` restore returns on a `vagrant_disabled` lab, and finds a
  working variant if not.
- Snapshot of running VMs (memory included) is acceptable; disk space is the user's concern.

## Left to the builder

- Exact console wording beyond the two prompts above.
- Where the snapshot logic lives (service vs console), as long as `ScenarioService` stays testable with a
  fake provider.
- `instance.json` field names.
