# goad-v2 Plan 1: Foundation and Templates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old multi-provider code with a new VMware-only core that builds, lists, tests and deletes versioned Packer VM templates (Server 2022, Server 2025, Windows 11, Ubuntu 24.04) through a scriptable `goad` CLI.

**Architecture:** goad runs in WSL2 and drives Windows binaries (`vmrun.exe`, `packer.exe`, `ipconfig.exe`) through one injectable subprocess runner, so every VMware call is unit-testable with a fake. A small VMware layer (`vmrun` wrapper, `.vmx` editor, parallel executor, guestinfo first-boot contract) is shared by templates now and by lab deploy in Plan 2. Templates are immutable folders `C:\goad\templates\<os>-v<n>\` ending on a powered-off `base` snapshot.

**Tech Stack:** Python 3.11+, argparse, rich, PyYAML, pypsrp, pytest; Packer 1.11+ with the `hashicorp/vmware` plugin (`vmware-iso` builder); VMware Workstation 17.5+ on Windows.

**Spec:** `docs/superpowers/specs/2026-11-20-vmware-core-rewrite-design.md`

This is plan 1 of 4. Plan 2: lab lifecycle (lab.yml, state, deploy, snapshot/reset). Plan 3: Ansible provisioning for the `1domain`, `2domains`, `2forests` labs. Plan 4: release gate.

## Global Constraints

- VMware Workstation only, Windows host, goad and Ansible in WSL2 (NAT mode). No Vagrant, no other provider.
- Branch: `goad-v2`. Old code is deleted, not kept beside the new.
- Templates: `win2022`, `win2025`, `win11`, `ubuntu2404`. Versioned `<os>-v<n>`, immutable once built, each ends on a powered-off snapshot named `base`.
- Default template root `C:\goad\templates\`; default lab VM root `C:\goad\lab\`.
- Default lab network `VMnet2`, `192.168.56.0/24`. goad checks it, never creates it.
- Windows templates: latest cumulative update at build time, VMware Tools, WinRM/PSRP enabled, AD DS + DNS + AD CS + RSAT features installed not configured (server templates only), extra root CAs imported, sysprepped.
- Win11 template: `HKLM\SYSTEM\Setup\LabConfig\BypassTPMCheck=1` and `BypassSecureBootCheck=1` in unattend, no vTPM, not encrypted.
- Every certificate (`*.cer`, `*.crt`) in the configured `ca_certs_dir` is imported into the machine root store (Windows `LocalMachine\Root`, Ubuntu `/usr/local/share/ca-certificates`).
- Uniform lab password `Aa1234567890!`.
- Prompts only on a TTY; `--yes` answers them; non-TTY without `--yes` fails with a clear message. Exit code 0 on success, non-zero on failure.
- Deleting a template a deployed lab uses is refused (Plan 1 has no labs: the check reads the state file through `goad/state.py` (Task 7) and treats a missing file as "no lab").

## Review Focus

1. Paths with spaces (`C:\Program Files (x86)\VMware\...`, user profile folders) passed between WSL and Windows: every argv is a list, never a shell string; `to_windows()` round-trips them.
2. `vmrun` returns exit code 0 with `Error:` on stdout for some failures: the wrapper must treat `Error:` output as failure.
3. A template build interrupted halfway leaves `C:\goad\templates\.build\<os>-v<n>`: the next build must not reuse its version number or pick it up in `template list`.
4. `template test` failing mid-way (no first-boot marker) must still power off and delete the test clone.
5. One VM failing in a parallel operation must not stop the others; the result names every failed VM.

Tests for each are added in the owning task (Tasks 2, 3, 7, 9, 5).

---

## File Structure

```
goad.py                         thin entry: from goad.cli import main; main()
pyproject.toml                  trimmed deps, script entry `goad = goad.cli:main`
goad/__init__.py
goad/cli.py                     argparse tree, TTY/--yes prompt helper, exit codes
goad/settings.py                ~/.goad/config.yml load + defaults
goad/host/runner.py             Runner (subprocess), Result, FakeRunner for tests
goad/host/paths.py              WSL <-> Windows path conversion
goad/host/checks.py             host checks: vmrun, packer, VMnet, disk space
goad/vmware/vmrun.py            Vmrun wrapper
goad/vmware/vmx.py              .vmx read/write preserving order
goad/vmware/parallel.py         run_parallel over VMs with per-VM result
goad/vmware/guestinfo.py        first-boot contract: keys, MAC derivation, marker
goad/templates/store.py         template registry: list, next version, delete, in-use check
goad/templates/build.py         packer invocation, finalize (base snapshot, move)
goad/templates/smoke.py         template test: clone, first boot, readiness, cleanup
goad/state.py                   minimal state-file reader (lab presence, templates used)
packer/common/variables.pkr.hcl shared vars (iso, output dir, ca dir, password)
packer/windows/windows.pkr.hcl  one vmware-iso source, parametrised per OS
packer/windows/<os>.pkrvars.hcl win2022, win2025, win11 values
packer/windows/answer/<os>/autounattend.xml
packer/windows/sysprep/unattend.xml       specialize + SetupComplete hook
packer/windows/scripts/*.ps1              winrm, updates, features, tools, ca, firstboot, cleanup
packer/ubuntu/ubuntu2404.pkr.hcl
packer/ubuntu/http/user-data, meta-data   autoinstall
packer/ubuntu/scripts/*.sh                tools, ca, cloud-init reset
tests/unit/...                  unit tests (FakeRunner, tmp_path)
tests/live/...                  marked `live`, run by hand on the host
```

---

### Task 1: Clean slate and skeleton

**Files:**
- Delete: `goad/` (all old modules), `template/`, `vagrant/`, `packer/proxmox/`, `packer/vagrant/`, `extensions/`, `scenarios/`, `ansible/`, `scripts/`, `workspace/`, `tests/` (old), `Dockerfile`, `goad_docker.sh`, `goad.sh`, `guacamole.yml`, `playbooks.yml`, `globalsettings.ini`, `noansible_requirements.yml`, `requirements*.yml`, `poetry.lock`, `ad/` (first move the reference data: `git mv ad/GOAD-Mini-Base/data labs/1domain/reference`, `git mv ad/GOAD-Light-Base/data labs/2domains/reference`, `git mv ad/GOAD-Base/data labs/2forests/reference`; Plans 2–3 turn each into `labs/<lab>/lab.yml` and then delete `reference/`)
- Keep: `LICENSE`, `README.md`, `docs/`, `labs/*/reference/`
- Create: `goad.py`, `goad/__init__.py`, `goad/cli.py`, `pyproject.toml`, `requirements-dev.txt`, `tests/__init__.py`, `tests/unit/test_cli.py`, `pytest.ini`

**Interfaces:**
- Produces: `goad.cli.main(argv: list[str] | None = None) -> int`; `goad.cli.confirm(question: str, yes: bool) -> bool` (raises `goad.cli.NeedsConfirmation` when stdin is not a TTY and `yes` is False); `goad.cli.build_parser() -> argparse.ArgumentParser` with subcommand groups `check`, `template` (`build`, `list`, `delete`, `test`). Each handler has signature `(args, ctx) -> int`; `ctx` is `goad.cli.Context(settings, runner)`.

- [ ] **Step 1: Delete old code** with `git rm -r` on the paths above. Verify: `git status --short | grep -v '^D' ` lists only the new `labs/*/reference/` renames and nothing else.
- [ ] **Step 2: Write `pyproject.toml`**: PEP 621 `[project]`, name `goad`, version `2.0.0.dev0`, `requires-python = ">=3.11"`, deps `rich>=13`, `PyYAML>=6`, `pypsrp>=0.8`; `[project.scripts] goad = "goad.cli:main"`; setuptools backend. `requirements-dev.txt`: `pytest>=8`. `pytest.ini`: `testpaths = tests`, marker `live: needs VMware host`, `addopts = -m "not live"`.
- [ ] **Step 3: Write failing tests** in `tests/unit/test_cli.py`:

```python
def test_help_lists_groups(capsys):
    with pytest.raises(SystemExit) as e: main(['--help'])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert 'check' in out and 'template' in out
def test_confirm_non_tty_without_yes_raises(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(NeedsConfirmation): confirm('Delete?', yes=False)
def test_confirm_yes_flag_skips_prompt(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert confirm('Delete?', yes=True) is True
def test_needs_confirmation_exit_code(monkeypatch):
    # a handler raising NeedsConfirmation -> main returns 2 and prints "use --yes"
def test_unknown_command_exit_code():
    with pytest.raises(SystemExit) as e: main(['nope'])
    assert e.value.code == 2
```

- [ ] **Step 4: Run** `pytest tests/unit/test_cli.py -v`. Expected: FAIL (`ModuleNotFoundError: goad.cli`).
- [ ] **Step 5: Implement `goad/cli.py`** with handlers as stubs returning 1 and printing `not implemented` (filled by later tasks). `main` returns handler's int; catches `NeedsConfirmation` → prints `confirmation needed: re-run with --yes` and returns 2; catches `GoadError` (define in `goad/__init__.py`) → prints message in red via rich and returns 1.
- [ ] **Step 6: Run** `pytest -v`. Expected: PASS.
- [ ] **Step 7: Commit** `chore: start goad-v2 from a clean slate with a new CLI skeleton`.

### Task 2: Settings and Windows paths

**Files:**
- Create: `goad/settings.py`, `goad/host/__init__.py`, `goad/host/paths.py`, `tests/unit/test_settings.py`, `tests/unit/test_paths.py`

**Interfaces:**
- Consumes: Task 1 `GoadError`.
- Produces:
  - `Settings` dataclass: `template_root: str` (Windows path, default `C:\goad\templates`), `lab_root: str` (default `C:\goad\lab`), `vmware_dir: str` (default `C:\Program Files (x86)\VMware\VMware Workstation`), `packer: str` (default `packer.exe`), `vmnet: str` (default `VMnet2`), `ip_range: str` (default `192.168.56`), `ca_certs_dir: str | None` (default None), `isos: dict[str, IsoSource]`, `state_dir: Path` (default `~/.goad`).
  - `IsoSource` dataclass: `url: str`, `checksum: str` (`sha256:<hex>`; `none` allowed only for local paths).
  - `load_settings(path: Path | None = None) -> Settings`: reads `~/.goad/config.yml` if present; unknown keys raise `GoadError` naming the key.
  - `to_windows(path: str | Path) -> str`, `to_wsl(path: str) -> Path`: pure functions (no `wslpath` call): `/mnt/c/x/y` ↔ `C:\x\y`; a path not under `/mnt/<drive>/` raises `GoadError` (`path not on a Windows drive`).
- Default ISO entries (copy into `settings.py`; verify the URLs resolve when implementing, replace with current Microsoft Evaluation Center links if moved, keep checksum `sha256:` placeholders `TODO-verify` only if the page publishes none, and document in README):
  - `win2022`: Microsoft eval ISO, `SERVER_EVAL_x64FRE_en-us.iso`
  - `win2025`: Microsoft eval ISO, `26100...SERVER_EVAL_x64FRE_en-us.iso`
  - `win11`: Windows 11 Enterprise eval ISO
  - `ubuntu2404`: `https://releases.ubuntu.com/24.04/ubuntu-24.04.x-live-server-amd64.iso` with its SHA256SUMS value

- [ ] **Step 1: Write failing tests**:

```python
def test_defaults_without_file(tmp_path):
    s = load_settings(tmp_path / 'missing.yml')
    assert s.vmnet == 'VMnet2' and s.ip_range == '192.168.56'
    assert s.template_root == r'C:\goad\templates'
def test_override_from_yaml(tmp_path): # vmnet: VMnet3 -> s.vmnet == 'VMnet3'
def test_unknown_key_rejected(tmp_path): # foo: 1 -> GoadError matching 'foo'
def test_to_windows_spaces():
    assert to_windows('/mnt/c/Program Files (x86)/VMware') == r'C:\Program Files (x86)\VMware'
def test_round_trip():
    assert to_windows(to_wsl(r'D:\goad\lab\dc01\dc01.vmx')) == r'D:\goad\lab\dc01\dc01.vmx'
def test_non_windows_path_rejected():
    with pytest.raises(GoadError): to_windows('/home/x/file')
```
- [ ] **Step 2: Run** `pytest tests/unit/test_settings.py tests/unit/test_paths.py -v`. Expected: FAIL (import errors).
- [ ] **Step 3: Implement** `goad/settings.py` and `goad/host/paths.py` per Interfaces.
- [ ] **Step 4: Run** same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(settings): config file with VMware-only defaults and Windows path conversion`.

### Task 3: Runner and vmrun wrapper

**Files:**
- Create: `goad/host/runner.py`, `goad/vmware/__init__.py`, `goad/vmware/vmrun.py`, `tests/unit/test_vmrun.py`

**Interfaces:**
- Consumes: `Settings.vmware_dir`, `to_wsl`, `to_windows`.
- Produces:
  - `Result(code: int, stdout: str, stderr: str)`, property `ok`.
  - `Runner.run(argv: list[str], timeout: float | None = None) -> Result` (subprocess, list argv, text mode, never `shell=True`).
  - `FakeRunner(Runner)`: `calls: list[list[str]]`; `respond(predicate: Callable[[list[str]], bool], result: Result)`; default `Result(0, '', '')`.
  - `Vmrun(runner: Runner, settings: Settings)`; every method takes Windows `.vmx` paths (str) and raises `VmrunError(GoadError)` with the `vmrun` output on failure:
    - `clone_linked(src_vmx, dest_vmx, snapshot: str, name: str) -> None` → `-T ws clone <src> <dest> linked -snapshot=<snapshot> -cloneName=<name>`
    - `start(vmx) -> None` (`start <vmx> nogui`), `stop(vmx, hard: bool = False) -> None` (`stop <vmx> soft|hard`)
    - `running() -> list[str]` (`list`, skips the `Total running VMs:` header, normalises case and slashes)
    - `snapshot(vmx, name)`, `revert(vmx, name)`, `delete_snapshot(vmx, name)`, `snapshots(vmx) -> list[str]` (`listSnapshots`, skips header)
    - `read_guest_var(vmx, key) -> str` (`readVariable <vmx> guestVar <key>`, empty string when unset)
    - `delete_vm(vmx)` (`deleteVM`)
  - Binary path: `to_wsl(settings.vmware_dir) / 'vmrun.exe'`.
- Failure rule (Review Focus 2): non-zero exit **or** stdout starting with `Error:` → `VmrunError`.

- [ ] **Step 1: Write failing tests** with `FakeRunner`:

```python
def test_clone_argv(vmrun, fake):
    vmrun.clone_linked(r'C:\t\win2025-v1\win2025-v1.vmx', r'C:\goad\lab\dc01\dc01.vmx', 'base', 'lab-dc01')
    assert fake.calls[-1][1:] == ['-T','ws','clone', r'C:\t\win2025-v1\win2025-v1.vmx',
        r'C:\goad\lab\dc01\dc01.vmx','linked','-snapshot=base','-cloneName=lab-dc01']
def test_error_on_stdout_with_exit_zero(vmrun, fake):
    fake.respond(lambda a: 'revertToSnapshot' in a, Result(0, 'Error: A snapshot with the name does not exist', ''))
    with pytest.raises(VmrunError, match='does not exist'): vmrun.revert('x.vmx', 'base')
def test_running_parses_list(vmrun, fake):
    fake.respond(lambda a: 'list' in a, Result(0, 'Total running VMs: 1\nC:\\goad\\lab\\DC01\\dc01.vmx\n', ''))
    assert vmrun.running() == ['c:/goad/lab/dc01/dc01.vmx']
def test_snapshots_parses_list(vmrun, fake): # 'Total snapshots: 2\nbase\ncp1\n' -> ['base','cp1']
def test_read_guest_var_unset_returns_empty(vmrun, fake): # Result(0,'','') -> ''
```
- [ ] **Step 2: Run** `pytest tests/unit/test_vmrun.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `runner.py` and `vmrun.py` per Interfaces.
- [ ] **Step 4: Run** same. Expected: PASS.
- [ ] **Step 5: Commit** `feat(vmware): vmrun wrapper over an injectable runner`.

### Task 4: VMX editor and guestinfo first-boot contract

**Files:**
- Create: `goad/vmware/vmx.py`, `goad/vmware/guestinfo.py`, `tests/unit/test_vmx.py`, `tests/unit/test_guestinfo.py`

**Interfaces:**
- Produces:
  - `Vmx.load(path: Path) -> Vmx`; `vmx[key]`, `vmx[key] = value`, `del vmx[key]`, `vmx.save()`. Keys case-insensitive on lookup; order and comments preserved; new keys appended; values written `key = "value"`.
  - `configure_hardware(vmx: Vmx, cpus: int, mem_mb: int, vmnet: str, lab_mac: str) -> None`: sets `numvcpus`, `memsize`, `ethernet0.present=TRUE`, `ethernet0.connectionType=nat`, `ethernet1.present=TRUE`, `ethernet1.connectionType=custom`, `ethernet1.vnet=<vmnet>`, `ethernet1.virtualDev=vmxnet3`, `ethernet1.addressType=static`, `ethernet1.address=<lab_mac>`.
  - `lab_mac(ip: str) -> str`: `00:50:56:3F:<o3 hex>:<o4 hex>` from the last two IP octets (VMware's static range is `00:50:56:00:00:00`–`00:50:56:3F:FF:FF`). Deterministic, unique per IP.
  - `GuestConfig(hostname: str, ip: str, prefix: int, gateway: str | None, dns: list[str], admin_password: str, lab_mac: str)`.
  - `write_guestinfo(vmx: Vmx, cfg: GuestConfig, os_family: Literal['windows','linux']) -> None`:
    - windows: `guestinfo.goad.hostname`, `.ip`, `.prefix`, `.dns` (comma-separated), `.password`, `.mac`; `guestinfo.goad.firstboot` deleted.
    - linux: `guestinfo.metadata` (base64 YAML: `instance-id: <hostname>`, `local-hostname`, `network` v2 matching `lab_mac`), `guestinfo.metadata.encoding=base64`, `guestinfo.userdata` (base64 cloud-config: chpasswd for user `goad`, `ssh_pwauth: true`, runcmd `vmware-rpctool "info-set guestinfo.goad.firstboot done"`), `guestinfo.userdata.encoding=base64`.
  - `FIRSTBOOT_KEY = 'goad.firstboot'`, `FIRSTBOOT_DONE = 'done'` (the guest sets it; `Vmrun.read_guest_var(vmx, FIRSTBOOT_KEY)` reads it).

- [ ] **Step 1: Write failing tests**:

```python
def test_roundtrip_preserves_order_and_comments(tmp_path): # load, set new key, save; original lines unchanged, new key last
def test_case_insensitive(tmp_path): # file has 'memSize = "2048"'; vmx['memsize'] == '2048'; set updates same line
def test_lab_mac(): assert lab_mac('192.168.56.10') == '00:50:56:3F:38:0A'
def test_hardware_keys(tmp_path): # configure_hardware(...,'VMnet2', mac) -> ethernet1.vnet == 'VMnet2', ethernet1.address == mac
def test_windows_guestinfo(tmp_path): # .ip, .dns == '192.168.56.10,192.168.56.11', no goad.firstboot
def test_linux_guestinfo_decodes(tmp_path): # base64-decode metadata -> yaml with network.ethernets.*.match.macaddress == mac (lowercase)
```
- [ ] **Step 2: Run** `pytest tests/unit/test_vmx.py tests/unit/test_guestinfo.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** same. Expected: PASS.
- [ ] **Step 5: Commit** `feat(vmware): vmx editor and guestinfo first-boot contract`.

### Task 5: Parallel VM operations

**Files:**
- Create: `goad/vmware/parallel.py`, `tests/unit/test_parallel.py`

**Interfaces:**
- Produces: `run_parallel(items: dict[str, T], fn: Callable[[str, T], None], label: str, max_workers: int = 8) -> ParallelResult`; `ParallelResult(ok: list[str], failed: dict[str, str])`, `ParallelResult.raise_if_failed(action: str)` → `GoadError('<action> failed on dc01: <msg>; dc02: <msg>')`. Every item runs even if others fail (Review Focus 5). Prints one rich line per item as it finishes: `<label> <name> ok (<seconds>s)` / `failed: <msg>`.

- [ ] **Step 1: Write failing tests**: `test_all_ok`; `test_one_failure_others_still_run` (fn raises for `dc02`; assert `ok == ['dc01','srv02']` set-equal, `'dc02' in failed`); `test_raise_if_failed_names_every_vm` (two failures, message contains both names).
- [ ] **Step 2: Run** `pytest tests/unit/test_parallel.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** with `concurrent.futures.ThreadPoolExecutor`.
- [ ] **Step 4: Run** same. Expected: PASS.
- [ ] **Step 5: Commit** `feat(vmware): parallel per-VM operations with per-VM results`.

### Task 6: Host checks and `goad check`

**Files:**
- Create: `goad/host/checks.py`, `tests/unit/test_checks.py`
- Modify: `goad/cli.py` (wire `check`)

**Interfaces:**
- Consumes: `Runner`, `Settings`, `to_wsl`.
- Produces: `Check(name: str, ok: bool, detail: str)`; `run_checks(runner, settings, need_packer: bool) -> list[Check]`:
  - `vmrun`: `vmrun.exe` exists under `vmware_dir`.
  - `packer` (only when `need_packer`): `<packer> version` exits 0 and reports `>= 1.11`.
  - `vmnet`: `ipconfig.exe` output has an adapter named `VMware Network Adapter <vmnet>` with IPv4 `<ip_range>.1`. On failure detail is: `create <vmnet> as host-only <ip_range>.0/24 in Virtual Network Editor (needs admin)`.
  - `disk`: free space on the drive of `template_root` ≥ 100 GB (via `shutil.disk_usage(to_wsl(drive root))`).
  - `ca_certs`: when `ca_certs_dir` set, the folder exists and has ≥ 1 `*.cer`/`*.crt`.
- `goad check` prints a table, returns 0 only if all ok.

- [ ] **Step 1: Write failing tests** with FakeRunner and a canned `ipconfig.exe` output: `test_vmnet_found`, `test_vmnet_missing_gives_fix_hint` (detail contains `Virtual Network Editor`), `test_vmnet_wrong_subnet_fails` (adapter present with `192.168.57.1`), `test_packer_too_old` (`Packer v1.9.4` → not ok), `test_check_command_exit_code`.
- [ ] **Step 2: Run** `pytest tests/unit/test_checks.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** and wire `check`.
- [ ] **Step 4: Run** same. Expected: PASS.
- [ ] **Step 5: Commit** `feat(check): host checks for vmrun, packer, VMnet, disk and CA certs`.

### Task 7: Template store and state reader

**Files:**
- Create: `goad/templates/__init__.py`, `goad/templates/store.py`, `goad/state.py`, `tests/unit/test_template_store.py`
- Modify: `goad/cli.py` (wire `template list`, `template delete`)

**Interfaces:**
- Consumes: `Settings`, `Vmrun`, `confirm`.
- Produces:
  - `OS_NAMES = ('win2022', 'win2025', 'win11', 'ubuntu2404')`; `OS_FAMILY = {'win2022':'windows', ..., 'ubuntu2404':'linux'}`.
  - `Template(name: str, os: str, version: int, vmx: str, built_at: str, packer_sha: str)`; metadata file `template.json` in the template folder.
  - `TemplateStore(settings, vmrun)`:
    - `list() -> list[Template]`: only folders matching `^(win2022|win2025|win11|ubuntu2404)-v(\d+)$` that hold `template.json`; `.build` ignored (Review Focus 3).
    - `latest(os) -> Template | None`.
    - `next_version(os) -> int`: 1 + max version seen in finished folders **and** in `.build/` (an aborted build burns its number).
    - `delete(name, yes: bool) -> None`: refuses with `GoadError('template <name> is used by the deployed lab')` when `state.templates_in_use()` contains it; asks `confirm`; `vmrun.delete_vm`, then removes the folder.
  - `goad/state.py`: `templates_in_use(settings) -> set[str]`: reads `<state_dir>/lab.json` key `templates` (list of names); missing file → empty set. (Plan 2 owns writing this file.)
- `template list` table columns: Name, OS, Built, In use.

- [ ] **Step 1: Write failing tests** with `tmp_path` as template root (use `to_wsl` monkeypatched to identity for tmp paths): `test_list_ignores_build_dir_and_foreign_folders`, `test_next_version_counts_aborted_build` (`win2025-v1` done, `.build/win2025-v2` exists → 3), `test_latest`, `test_delete_in_use_refused` (lab.json lists `win2025-v1`), `test_delete_non_tty_needs_yes`.
- [ ] **Step 2: Run** `pytest tests/unit/test_template_store.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** and wire the two CLI commands.
- [ ] **Step 4: Run** same. Expected: PASS.
- [ ] **Step 5: Commit** `feat(templates): versioned template store with in-use protection`.

### Task 8: Packer templates and `goad template build`

**Files:**
- Create: everything under `packer/` listed in File Structure; `goad/templates/build.py`; `tests/unit/test_template_build.py`; `tests/live/test_template_build_live.py`
- Modify: `goad/cli.py` (wire `template build <os>`)

**Interfaces:**
- Consumes: `TemplateStore.next_version`, `Vmrun.snapshot`, `Runner`, `Settings`, `to_windows`.
- Produces: `build_template(os: str, ctx) -> Template`.

Decisions for the Packer side (the implementer writes the files):
- One Windows source `vmware-iso.windows` driven by `<os>.pkrvars.hcl`: `guest_os_type` (`windows2019srvnext-64` for 2022/2025, `windows11-64` for win11), `firmware = "efi"`, `cpus=2`, `memory=4096`, `disk_size=61440`, `disk_adapter_type="nvme"`, `network_adapter_type="vmxnet3"`, `communicator="winrm"`, `winrm_username="goad-setup"`, `winrm_password=var.password`, `headless=true`, `output_directory = <template_root>\.build\<os>-v<n>`, `vm_name = <os>-v<n>`, `shutdown_command` runs sysprep: `C:\Windows\System32\Sysprep\sysprep.exe /generalize /oobe /shutdown /unattend:C:\goad\unattend.xml`.
- Autounattend (per OS answer folder, delivered via `cd_files`): creates local admin `goad-setup` with `var.password`, autologon once, enables WinRM over HTTP basic for Packer only, Win11 adds the two `LabConfig` bypass keys in windowsPE.
- Provisioner scripts, in order: `install-vmware-tools.ps1` (from the Workstation `windows.iso` attached as second CD), `import-ca.ps1` (every file in `cd_files` folder `ca\`), `install-updates.ps1` (PSWindowsUpdate or `UsoClient`-free method of the implementer's choice; loops reboots via `windows-restart` until none pending), `install-features.ps1` (servers only: `AD-Domain-Services, DNS, ADCS-Cert-Authority, RSAT-AD-Tools, RSAT-DNS-Server, RSAT-ADCS -IncludeManagementTools`), `enable-psrp.ps1` (WinRM HTTP 5985, `Enable-PSRemoting -Force`, firewall rule for all profiles, `LocalAccountTokenFilterPolicy=1`), `copy-firstboot.ps1` (copies `firstboot.ps1` to `C:\goad\`, `SetupComplete.cmd` to `C:\Windows\Setup\Scripts\`, `unattend.xml` to `C:\goad\`), `cleanup.ps1` (component cleanup, defrag skip, `sdelete`-free zeroing optional).
- `firstboot.ps1` contract (runs from `SetupComplete.cmd` as SYSTEM after specialize): read `guestinfo.goad.{hostname,ip,prefix,dns,password,mac}` with `& "C:\Program Files\VMware\VMware Tools\rpctool.exe" "info-get guestinfo.goad.<k>"`; set the static IP/DNS on the adapter whose MAC equals `mac`; set local `Administrator` password and enable the account; `Rename-Computer`; set `guestinfo.goad.firstboot` to `done` with `info-set` **after** the rename reboot (schedule a one-shot startup task that sets it and deletes itself); reboot. If `guestinfo.goad.ip` is empty (template build itself), exit 0 without changes.
- `sysprep/unattend.xml`: `specialize` sets `ComputerName=*` (renamed later by firstboot), `oobeSystem` skips all OOBE pages, `Administrator` password `var.password`, timezone UTC.
- Ubuntu source `vmware-iso.ubuntu2404`: `guest_os_type="ubuntu-64"`, `firmware="efi"`, autoinstall via `http_directory`, user `goad` / `var.password`, `ssh_username="goad"`; scripts install `open-vm-tools`, import CAs into `/usr/local/share/ca-certificates/` + `update-ca-certificates`, enable cloud-init datasource `VMware` (`/etc/cloud/cloud.cfg.d/99-vmware.cfg`: `datasource_list: [ VMware, None ]`), then `cloud-init clean --logs --machine-id` and shutdown.
- Packer variables passed by goad: `iso_url`, `iso_checksum`, `output_directory`, `vm_name`, `password` (`Aa1234567890!`), `ca_dir` (Windows path or empty).

goad side (`build.py`):
1. `run_checks(need_packer=True)` must pass.
2. `n = store.next_version(os)`; out dir `<template_root>\.build\<os>-v<n>`.
3. `packer.exe init <packer dir>` then `packer.exe build -force -var-file=<os>.pkrvars.hcl -var ... <dir>`; run with cwd = Windows path of the repo `packer/` folder; stream output to the terminal and to `<state_dir>/logs/template-<os>-v<n>.log`.
4. On success: `vmrun snapshot <vmx> base` (VM is powered off after sysprep shutdown), write `template.json` (`packer_sha` = `git rev-parse HEAD:packer`), move folder to `<template_root>\<os>-v<n>`.
5. On failure: leave `.build/<os>-v<n>` for inspection, raise `GoadError` naming the log file.

- [ ] **Step 1: Write failing unit tests** (FakeRunner, no packer): `test_build_argv` (asserts `init` then `build` with `-var vm_name=win2025-v1` and `output_directory` ending `\.build\win2025-v1`), `test_success_takes_base_snapshot_and_moves`, `test_failure_keeps_build_dir_and_names_log`, `test_unknown_os_rejected`.
- [ ] **Step 2: Run** `pytest tests/unit/test_template_build.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `build.py`; write the Packer files.
- [ ] **Step 4: Run** unit tests. Expected: PASS. Run `packer.exe validate -var-file=...` for each OS (from WSL via interop). Expected: `The configuration is valid.` ×4.
- [ ] **Step 5: Live test** (`tests/live/test_template_build_live.py`, `pytest -m live -k build`): builds `win2025`, asserts `template list` shows `win2025-v1` and `vmrun listSnapshots` shows `base`. Run it once by hand; record build time in the commit message.
- [ ] **Step 6: Commit** `feat(templates): packer templates for win2022, win2025, win11, ubuntu2404 and template build`.

### Task 9: `goad template test`

**Files:**
- Create: `goad/templates/smoke.py`, `tests/unit/test_template_smoke.py`, `tests/live/test_template_smoke_live.py`
- Modify: `goad/cli.py` (wire `template test <os>`)

**Interfaces:**
- Consumes: `TemplateStore.latest`, `Vmrun.clone_linked/start/stop/read_guest_var/delete_vm`, `Vmx`, `configure_hardware`, `write_guestinfo`, `lab_mac`, `FIRSTBOOT_KEY`.
- Produces:
  - `wait_firstboot(vmrun, vmx, timeout=900, interval=10) -> None` (raises `GoadError('first boot did not finish in 900s')`).
  - `wait_port(ip, port, timeout=300) -> None`.
  - `check_psrp(ip, user, password) -> None` (pypsrp `Client(...).execute_ps('hostname')` returns the expected hostname) and `check_ssh(ip)` (TCP 22 open + banner starts `SSH-2.0`).
  - `smoke_test(os, ctx) -> float` (seconds). These four `wait_*`/`check_*` functions are reused by Plan 2 deploy.
- Test VM: `<lab_root>\.smoke\<os>\<os>.vmx`, hostname `smoke-<os>` (Windows ≤ 15 chars: `smoke-win2025`), IP `<ip_range>.250`, 2 CPU, 4096 MB.
- Cleanup (Review Focus 4): `try/finally` → `stop hard` (ignore error if already off) → `delete_vm` → remove folder. Refuses to start if `<ip_range>.250` answers ping already.

- [ ] **Step 1: Write failing unit tests**: `test_smoke_clones_from_latest_base` (argv), `test_smoke_cleans_up_on_firstboot_timeout` (read_guest_var always `''`, tiny timeout; assert `stop` and `deleteVM` were called and `GoadError` raised), `test_no_template_built` (`GoadError` with `goad template build <os>` hint).
- [ ] **Step 2: Run** `pytest tests/unit/test_template_smoke.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `smoke.py` and wire the command; output: one line per phase with seconds, final `template <name> ok in <s>s`.
- [ ] **Step 4: Run** unit tests. Expected: PASS.
- [ ] **Step 5: Live** `pytest -m live -k smoke` for each OS after building it (`goad template build <os>`). Expected: 4 passes. Note each duration.
- [ ] **Step 6: Commit** `feat(templates): template test clones, first-boots, checks and cleans up`.

### Task 10: README for goad-v2

**Files:**
- Modify: `README.md` (rewrite)

- [ ] **Step 1: Rewrite** README: what goad-v2 is (one VMware Workstation lab, Packer + Ansible, managed as one unit), host requirements (Workstation 17.5+, WSL2 NAT mode, Packer 1.11+, VMnet2 host-only `192.168.56.0/24` created once in Virtual Network Editor), install (`pip install -e .` in a venv), `~/.goad/config.yml` keys from `Settings` with defaults, the CA cert folder for TLS-intercepting networks, `goad check`, `goad template build|list|test|delete`. State that labs, scenarios and extensions arrive in later plans; the old tool lives on `main`.
- [ ] **Step 2: Verify** every command in the README exists: `goad --help`, `goad template --help`.
- [ ] **Step 3: Commit** `docs: README for goad-v2 foundation`.
