# Scenario and Extension Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer a whole-lab named snapshot before `enable_scenario` / `install_extension`, and offer a revert (with a report of what is lost and restored) before `disable_scenario` / the new `remove_extension`.

**Architecture:** `instance.json` gets an ordered `snapshots` list of records that capture goad's view of the lab (scenarios, `vagrant_disabled`, `extensions`) at snapshot time, plus a never-reused counter. A new `LabSnapshots` class owns take / find / report / revert / forget against a provider-neutral snapshot API that the Vagrant provider implements with `vagrant snapshot`. `ScenarioService` and a new `ExtensionService` call it through an `ask` callable; the console builds `ask` from the TTY state and the `--no-snapshot` / `--yes` flags.

**Tech Stack:** Python 3 (goad CLI, `cmd`-based console), pytest, Vagrant + `vagrant-vmware-desktop`, VMware Workstation.

**Spec:** `docs/superpowers/specs/2026-11-19-scenario-snapshots-design.md`

## Global Constraints

- Snapshot and revert are always whole-lab; never restore a subset of the VMs that existed at snapshot time.
- Names: `scn-<seq>-<scenario>@<host>` and `ext-<seq>-<extension>`; `<seq>` two digits zero padded, grows past 99, one shared counter, advanced only when a snapshot is taken, never reused.
- Prompts (exact text):
  - `Take a lab snapshot before enabling <scenario>@<host>? (y/N)`
  - `Take a lab snapshot before installing extension <name>? (y/N)`
  - `Revert the lab to <snapshot> instead of disabling? (y/N)`
  - `Revert the lab to <snapshot> instead of removing? (y/N)`
  - `Remove extension <name> without revert? (y/N)`
- Default answer is N everywhere.
- No prompt when stdin is not a TTY or `--no-snapshot` is given; `remove_extension` without a TTY refuses unless `--yes`.
- Restore uses `vagrant snapshot restore --no-provision`.
- VMs of extensions not in the record are destroyed (`vagrant destroy -f <vm>`) before the instance folder is regenerated.
- Providers without named snapshots behave as `--no-snapshot`.
- Live verification on VMware Workstation only (user only uses VMware Vagrant).
- Commits on a feature branch `feat/lab-snapshots`; end commit messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never commit `.claude/` or `.superpowers/`.

## Review Focus

1. **Revert after middle removals:** A(snap) → B(snap) → disable A by uninstall → revert B: instance must list nothing, and A's snapshot must be gone. Test in Task 3 (`test_revert_restores_record_state_after_middle_uninstall`).
2. **Partial snapshot save:** `vagrant snapshot save` fails after some VMs got the snapshot; the enable must stop and no VM may keep the partial snapshot. Test in Task 3 (`test_take_failure_deletes_partial_snapshot`).
3. **Restore on a `vagrant_disabled` lab:** restore may wait for the guest communicator with the disabled vagrant user. Live in Task 7; the provider must not hang (bounded by `--no-start` + `vagrant up --no-provision` fallback if needed, ruled live).
4. **Extension VM destroy ordering:** destroy must run while the generated Vagrantfile still defines the VM. Test in Task 5 (`test_remove_destroys_before_disable`).
5. **Scripted runs never block:** harness pipes commands into `goad.py`; no `input()` may be reached without a TTY. Test in Task 6 (`test_no_tty_never_prompts`).

---

### Task 1: Snapshot records in the instance

**Files:**
- Create: `goad/lab_snapshot_record.py`
- Modify: `goad/instance.py` (constructor, `save_json_instance`, new methods), `goad/instances.py:15-33` (load new keys)
- Test: `tests/test_snapshot_records.py`

**Interfaces:**
- Produces:
  - `@dataclass SnapshotRecord(name: str, taken_for: str, scenarios: List[dict], vagrant_disabled: bool, extensions: List[str])` in `goad/lab_snapshot_record.py`; `taken_for` is `"<name>@<target>"` or `"extension:<name>"`; `scenarios` holds `asdict(EnabledScenario)` items. `SnapshotRecord.from_dict(d) -> SnapshotRecord` ignores unknown keys.
  - `LabInstance.snapshots: List[SnapshotRecord]`, `LabInstance.snapshot_seq: int` (next number to use, starts at 1).
  - `LabInstance.next_snapshot_name(prefix: str, label: str) -> str` returns `f"{prefix}-{seq:02d}-{label}"` and advances and saves `snapshot_seq`.
  - `LabInstance.add_snapshot_record(record)`, `LabInstance.remove_snapshot_records(names: Iterable[str])`, `LabInstance.find_snapshot_record(taken_for) -> Optional[SnapshotRecord]` (latest match).
  - `LabInstance.capture_state(name, taken_for) -> SnapshotRecord` (copies current scenarios / vagrant_disabled / extensions, deep copy).
  - `LabInstance.apply_state(record)` sets `scenarios`, `vagrant_disabled`, `extensions` from the record, saves, and calls `update_instance_folder()`.
  - `instance.json` keys: `snapshots` (list of `asdict(SnapshotRecord)`), `snapshot_seq`.

- [ ] **Step 1: Write the failing tests** in `tests/test_snapshot_records.py` using the `workspace` / `tmp_instance` fixture pattern of `tests/test_instance_scenarios.py`:
  - `test_snapshot_records_round_trip`: add a record, reload through `LabInstances(None)`, `instance.snapshots == [record]` and `snapshot_seq` kept.
  - `test_legacy_instance_has_no_snapshots`: an `instance.json` without the keys loads with `snapshots == []`, `snapshot_seq == 1`.
  - `test_snapshot_name_counter_never_reused`: `next_snapshot_name("scn", "esc4@dc01") == "scn-01-esc4@dc01"`, next is `scn-02-...`; after `remove_snapshot_records(["scn-02-..."])` the next is `scn-03-...`; at seq 100 the name is `scn-100-x`.
  - `test_capture_state_is_a_copy`: mutate `instance.scenarios` after `capture_state`; record unchanged.
  - `test_apply_state_restores_fields` (monkeypatch `update_instance_folder` to record the call): scenarios, `vagrant_disabled`, `extensions` equal the record's; `update_instance_folder` called once.
  - `test_record_ignores_unknown_keys`: `SnapshotRecord.from_dict({... , "future": 1})` works.
- [ ] **Step 2: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_snapshot_records.py` — Expected: FAIL (`ModuleNotFoundError: goad.lab_snapshot_record`).
- [ ] **Step 3: Implement** the dataclass and the instance members above; `LabInstances._init_instances` reads `instance_info.get('snapshots', [])` and `instance_info.get('snapshot_seq', 1)` and passes them to `LabInstance(...)` as new keyword args `snapshots=None, snapshot_seq=1`.
- [ ] **Step 4: Run** the same command — Expected: PASS. Then full suite `~/.goad/.venv/bin/python -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat(snapshots): snapshot records in instance.json`.

### Task 2: Named snapshot API on the Vagrant provider

**Files:**
- Modify: `goad/provider/provider.py` (base: `supports_named_snapshots() -> False` and the four methods raising `NotImplementedError`), `goad/provider/vagrant/vagrant.py`, `goad/command/cmd.py` (add `run_vagrant_output(args, path) -> Tuple[bool, str]`)
- Create: `goad/vagrant_names.py` (`vm_names_in(vagrantfile_text: str) -> List[str]`)
- Test: `tests/test_vagrant_snapshots.py`, fixture `tests/fixtures/vagrant_snapshot_list.txt`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces (on `Provider`, implemented by `VagrantProvider`; `VmwareProvider` returns `True` from `supports_named_snapshots`, other Vagrant providers keep `False` — VMware-only scope):
  - `supports_named_snapshots() -> bool`
  - `vm_names() -> List[str]`: names in the instance's generated Vagrantfile (`self.path/Vagrantfile`).
  - `snapshot_save(name: str) -> bool`: `vagrant snapshot save <name>` (whole environment).
  - `snapshot_list() -> Dict[str, List[str]]`: VM name → snapshot names, parsed from `vagrant snapshot list --machine-readable`.
  - `snapshot_restore(name: str, vms: List[str]) -> bool`: per VM `vagrant snapshot restore --no-provision <vm> <name>`; stops at the first failure.
  - `snapshot_delete(name: str, vms: List[str]) -> bool`: per VM `vagrant snapshot delete <vm> <name>`.
  - `destroy_vms(vms: List[str]) -> bool`: per VM `vagrant destroy -f <vm>`.
  - `extension_vm_names(extension_name, lab_name, ip_range) -> List[str]`: renders the extension's provider Vagrantfile with Jinja (`lab_name`, `ip_range`) and returns `vm_names_in(...)`.
  - `vm_names_in` matches `:name\s*=>\s*"([^"]+)"`.

- [ ] **Step 1: Capture the real output.** On the provisioned GOAD-Base instance (`workspace/d1e0a8-goad-base-vmware/provider`) run `vagrant.exe snapshot save GOAD-Base-DC01 probe-a`, then `vagrant.exe snapshot list --machine-readable > tests/fixtures/vagrant_snapshot_list.txt`, then `vagrant.exe snapshot delete GOAD-Base-DC01 probe-a`. Expected: the fixture shows `probe-a` for DC01 and the "no snapshots" line for the other VMs. Ledger the exact line format.
- [ ] **Step 2: Write the failing tests** with a fake `command` object that records `run_vagrant` / `run_vagrant_output` args and returns scripted results:
  - `test_snapshot_list_parses_fixture`: `{"GOAD-Base-DC01": ["probe-a"], "GOAD-Base-DC02": [], ...}`.
  - `test_snapshot_save_args`: `["snapshot", "save", "scn-01-x"]`.
  - `test_snapshot_restore_per_vm_no_provision`: two VMs → two calls `["snapshot", "restore", "--no-provision", vm, name]`; a failing first call stops before the second and returns False.
  - `test_snapshot_delete_per_vm`, `test_destroy_vms_force`.
  - `test_vm_names_in_extension_vagrantfile`: rendering `extensions/guacamole/providers/vmware/Vagrantfile` with `lab_name="GOAD-Base"` → `["GOAD-Base-GUACAMOLE"]`.
  - `test_only_vmware_supports_named_snapshots`: `VmwareProvider` True; `VirtualboxProvider` and base `Provider` False.
- [ ] **Step 3: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_vagrant_snapshots.py` — Expected: FAIL.
- [ ] **Step 4: Implement.** `run_vagrant_output` runs the command with `capture_output=True, text=True` and returns `(returncode == 0, stdout)`.
- [ ] **Step 5: Run** the test file, then the full suite — Expected: PASS.
- [ ] **Step 6: Commit** `feat(snapshots): named snapshot API on the vagrant provider`.

### Task 3: LabSnapshots — take, report, revert, forget

**Files:**
- Create: `goad/lab_snapshots.py`
- Test: `tests/test_lab_snapshots.py`

**Interfaces:**
- Consumes: Task 1 instance members, Task 2 provider methods.
- Produces:
  - `@dataclass RevertReport(record: SnapshotRecord, removed: str, lost_scenarios: List[str], lost_extensions: Dict[str, List[str]], restored_scenarios: List[str], deleted_snapshots: List[str], vagrant_change: Optional[str])` — `removed` is the record's `taken_for`; `lost_scenarios` = current entry keys not in the record and not `removed`; `lost_extensions` = current extensions not in the record → their VM names; `restored_scenarios` = record entry keys not currently enabled; `deleted_snapshots` = names of records after the revert point; `vagrant_change` = `"vagrant account: enabled again"` when the record has `vagrant_disabled False` and the instance `True`, `"vagrant account: disabled again"` for the reverse, else None.
  - `RevertReport.lines() -> List[str]`: the stack (oldest first, `<- revert point`, `deleted` marks) then `removed:`, `lost:`, `restored:` lines and the vagrant/extension lines, as in the spec's example.
  - `class LabSnapshots(instance, provider, lab_name, ip_range)`:
    - `supported() -> bool` (provider `supports_named_snapshots()`).
    - `take(prefix, label, taken_for) -> Optional[SnapshotRecord]`: name from `instance.next_snapshot_name`, `provider.snapshot_save`; on failure call `snapshot_delete(name, <VMs that list it>)` and return None; on success `capture_state` + `add_snapshot_record` and return the record.
    - `find(taken_for) -> Optional[SnapshotRecord]`.
    - `revertable(record) -> Optional[str]`: None when `snapshot_list()` shows the name on every VM that existed at snapshot time (current `vm_names()` minus the VMs of extensions not in the record); otherwise the reason (`snapshot <name> missing on <vm>`).
    - `report(record) -> RevertReport` (pure, no provider calls except `extension_vm_names`).
    - `revert(record) -> bool`: `destroy_vms(lost extension VMs)`; `snapshot_restore(record.name, covered VMs)`; on success `instance.apply_state(record)`, delete the snapshots of the revert point and every later record from the VMs that list them, `remove_snapshot_records(...)`; return True. On any provider failure return False with `instance.json` unchanged.
    - `forget(taken_for)`: delete that record's snapshot from the VMs that list it and remove the record (no-op when none).

- [ ] **Step 1: Write the failing tests** with a fake provider (in-memory `{vm: [snapshots]}`, failure switches) and a real `LabInstance` in a tmp workspace (`update_instance_folder` monkeypatched):
  - `test_take_records_state_and_name`
  - `test_take_failure_deletes_partial_snapshot` (fake save puts the snapshot on DC01 then fails → after `take`, no VM lists it, no record, returns None)
  - `test_report_lost_restored_removed` (spec example: maq@dc02, rbcd@srv02 snapshot, esc1@dc01 no snapshot, esc4@dc01 snapshot, smb-signing-off@srv02 disabled after the rbcd snapshot → lost `esc1@dc01, esc4@dc01`, restored `smb-signing-off@srv02`, deleted `scn-04-esc4@dc01`)
  - `test_report_vagrant_change_and_lost_extension_vms`
  - `test_revertable_missing_snapshot_reason`
  - `test_revertable_ignores_vms_of_later_extensions`
  - `test_revert_restores_record_state_after_middle_uninstall` (Review Focus 1)
  - `test_revert_destroys_later_extension_vms_then_restores_the_rest` (order of fake provider calls)
  - `test_revert_failure_leaves_instance_unchanged`
  - `test_forget_deletes_snapshot_and_record`
- [ ] **Step 2: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_lab_snapshots.py` — Expected: FAIL.
- [ ] **Step 3: Implement** `goad/lab_snapshots.py`.
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat(snapshots): take, report and revert lab snapshots`.

### Task 4: Scenario service integration

**Files:**
- Modify: `goad/scenario_service.py`
- Test: `tests/test_scenario_service.py` (extend; reuse `FakeProvisioner`, `FakeInstance` gains the Task 1 members or the tests use a real instance)

**Interfaces:**
- Consumes: `LabSnapshots` (Task 3).
- Produces: `ScenarioService(instance, lab, provisioner, snapshots=None, ask=None)`; `ask(prompt: str) -> bool`; no prompts when `snapshots is None`, `ask is None`, or `not snapshots.supported()`. `listing()` rows gain a fourth column: snapshot name or `''`.

Behaviour (spec §Enable, §Disable, §Other scenario commands):
- `enable`: after `check_enable` succeeds, `ask(Take a lab snapshot before enabling <name>@<target>? (y/N))`; `y` → `snapshots.take("scn", f"{name}@{target}", f"{name}@{target}")`; None → log and return False without running the install. Install fails and cleanup succeeds → `snapshots.forget(key)`. Install and cleanup fail → entry dirty, snapshot kept.
- `disable`: before the dependents check, `record = snapshots.find(entry.key)`; if a record exists and `revertable(record)` is None → log `report(record).lines()`, `ask(Revert the lab to <name> instead of disabling? (y/N))`; `y` → `return snapshots.revert(record)`. A non-None reason is logged, then the uninstall path runs.
- Every uninstall-path removal (`_disable_entry` success, `reset`) calls `snapshots.forget(entry.key)`.

- [ ] **Step 1: Write the failing tests:** `test_enable_takes_snapshot_on_yes`, `test_enable_no_prompt_without_ask`, `test_enable_stops_when_snapshot_fails`, `test_failed_enable_with_clean_cleanup_forgets_snapshot`, `test_failed_enable_dirty_keeps_snapshot`, `test_disable_offers_revert_and_reverts_on_yes` (no uninstall call made), `test_disable_declined_revert_uninstalls_and_forgets`, `test_disable_missing_snapshot_logs_and_uninstalls`, `test_reset_forgets_snapshots`, `test_listing_shows_snapshot_column`.
- [ ] **Step 2: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_scenario_service.py` — Expected: new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat(snapshots): snapshot and revert around scenarios`.

### Task 5: Extension service with install and remove

**Files:**
- Create: `goad/extension_service.py`
- Test: `tests/test_extension_service.py`

**Interfaces:**
- Consumes: `LabSnapshots` (Task 3), provider `install()`, `extension_vm_names`, `destroy_vms` (Task 2), `instance.enable_extension` / `disable_extension`.
- Produces: `ExtensionService(instance, provider, provision: Callable[[str], bool], snapshots=None, ask=None)`:
  - `install(name) -> bool`: optional snapshot (`take("ext", name, f"extension:{name}")`, None → stop), `instance.enable_extension(name)`, `provider.install()`, `provision(name)`. A failure keeps the snapshot.
  - `remove(name, yes=False) -> bool`: not enabled → error. Revert offer as for scenarios (`Revert the lab to <snapshot> instead of removing? (y/N)`) when a revertable record exists. Otherwise log the warning `agents and domain objects the extension pushed to the lab stay (computer accounts, DNS records, agents)`, and unless `yes`, `ask(Remove extension <name> without revert? (y/N))` (no `ask` and no `yes` → refuse with `use --yes`). Then `provider.destroy_vms(extension_vm_names(...))` and only after it succeeds `instance.disable_extension(name)` and `snapshots.forget(f"extension:{name}")`.

- [ ] **Step 1: Write the failing tests:** `test_install_snapshot_then_up_then_provision` (call order), `test_install_stops_when_snapshot_fails`, `test_remove_offers_revert`, `test_remove_without_snapshot_destroys_vms_and_disables`, `test_remove_destroys_before_disable` (Review Focus 4: `disable_extension` called after `destroy_vms`; destroy failure → extension still enabled), `test_remove_declined_confirmation_does_nothing`, `test_remove_without_ask_needs_yes`.
- [ ] **Step 2: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_extension_service.py` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the file and the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat(snapshots): extension install and remove with snapshots`.

### Task 6: Console wiring and docs

**Files:**
- Modify: `goad.py` (`do_enable_scenario`, `do_disable_scenario`, `do_install_extension`, new `do_remove_extension` + `complete_remove_extension`, `_scenario_service`, `do_list_scenarios` table column), `goad/menu.py` (menu entry for `remove_extension`), `docs/mkdocs/docs/scenarios.md` (Snapshots section), the extensions doc page under `docs/mkdocs/docs/` that lists `install_extension` (add `remove_extension`)
- Test: `tests/test_goad_cli.py` (extend)

**Interfaces:**
- Consumes: Tasks 4 and 5.
- Produces: `Goad._ask(no_snapshot: bool) -> Optional[Callable[[str], bool]]` returning `Utils.confirm`-based ask only when `sys.stdin.isatty()` and not `no_snapshot`; `--no-snapshot` accepted on the four commands, `--yes` on `remove_extension`; `do_install_extension` delegates to `ExtensionService.install` with `provision=self.do_provision_extension`-equivalent returning bool.

- [ ] **Step 1: Write the failing tests** (pattern of `make_cli`): `test_no_tty_never_prompts` (monkeypatch `sys.stdin.isatty` False and `builtins.input` to raise → enable/disable/install/remove reach no `input`), `test_no_snapshot_flag_disables_ask`, `test_remove_extension_without_tty_needs_yes`, `test_flags_are_stripped_from_positional_args`.
- [ ] **Step 2: Run** `~/.goad/.venv/bin/python -m pytest -q tests/test_goad_cli.py` — Expected: new tests FAIL.
- [ ] **Step 3: Implement** the console changes, then write the docs: a "Snapshots" section in `scenarios.md` (prompts, naming, report example from the spec, revert vs disable, `--no-snapshot`, non-TTY rule, VMware-only) and `remove_extension` in the extensions page (revert offer, fallback destroy, residue warning, `--yes`).
- [ ] **Step 4: Run** the full suite — Expected: PASS.
- [ ] **Step 5: Commit** `feat(snapshots): console commands and docs`.

### Task 7: Live verification on GOAD-Base

**Files:**
- Ledger only (no code unless a ruling needs it; then RED→GREEN in the owning module and commit).

Run in an interactive terminal the user does not need to attend: drive the console with a pseudo-TTY (`script -qc "python goad.py" /dev/null` fed by a here-doc) so prompts appear, on instance `d1e0a8-goad-base-vmware` (`vagrant_disabled: true`).

- [ ] **Step 1: Scenario revert.** `enable_scenario maq dc02` (y, snapshot), `enable_scenario rbcd srv02` (y), `enable_scenario esc1 dc01` (n), `disable_scenario rbcd srv02` → report shows `lost: esc1@dc01`, revert y. Expected: restore returns (no hang) on the `vagrant_disabled` lab; `instance.json` lists only `maq@dc02`; `vagrant snapshot list` shows only `scn-01-maq@dc02`; harness snapshot (`scripts/scenario_snapshot.ps1` via `tests/live/run_scenario_cycle.sh` helpers or a direct ad-hoc run) shows no esc1/rbcd objects. If restore hangs on the communicator: rule it (`--no-start` then `vmrun start`, or another variant), fix in Task 2's provider with a test, re-run.
- [ ] **Step 2: Middle removal.** `enable_scenario smb-signing-off srv02` (y), `disable_scenario maq dc02` (n → uninstall; its snapshot deleted), `disable_scenario smb-signing-off srv02` → report, revert y. Expected: `instance.json` scenarios empty; lab has MAQ 0 on north.
- [ ] **Step 3: Extension.** `install_extension guacamole` (y), `enable_scenario mdns srv02` (y), `remove_extension guacamole` → report shows `lost: mdns@srv02` and the GUACAMOLE VM; revert y. Expected: GUACAMOLE VM destroyed, Vagrantfile without it, `extensions == []`, no snapshots left. Then `install_extension guacamole` (n), `remove_extension guacamole` (n → confirmation y). Expected: VM destroyed, extension disabled.
- [ ] **Step 4: Scripted path.** Run the existing harness `tests/live/run_scenario_cycle.sh d1e0a8-goad-base-vmware smb-signing-off` (no TTY). Expected: RESULT PASS, no prompt, no snapshot taken.
- [ ] **Step 5: Ledger** the results; final suite run with `task-done`.
