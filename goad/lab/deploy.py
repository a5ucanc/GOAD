"""Lab deploy: ordered, resumable steps. Each finished step is saved in lab.json."""
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from rich.console import Console
from rich.table import Table

from goad import GoadError
from goad.host.checks import run_checks
from goad.host.paths import to_wsl
from goad.lab.context import Lab, vm_folder, vm_path
from goad.lab.definition import load_lab, shipped_lab
from goad.lab.power import READY_TIMEOUT, port_for, start_all, stop_all, wait_ready
from goad.lab.provision import provision
from goad.lab.remote import remove_setup_account
from goad.settings import Settings
from goad.state import STEPS, HostState, LabState, SnapshotRecord, load_state, save_state, working_lab_path
from goad.templates.smoke import check_psrp, check_ssh, FIRSTBOOT_TIMEOUT, firstboot_marker, is_up, wait_port
from goad.templates.store import TemplateStore
from goad.vmware.guestinfo import FIRSTBOOT_DONE, FIRSTBOOT_FAILED, GuestConfig, configure_hardware, lab_mac, write_guestinfo
from goad.vmware.parallel import run_parallel
from goad.vmware.vmrun import Vmrun
from goad.vmware.vmx import Vmx

console = Console()

# a host that finished first boot in an earlier run answers within this many seconds
PROBE_TIMEOUT = 10
FIRSTBOOT_POLL = 10


@dataclass
class Probes:
    """Network and host probes, replaceable in tests."""
    is_up: Callable = is_up
    firstboot_marker: Callable = firstboot_marker
    sleep: Callable = time.sleep
    wait_port: Callable = wait_port
    check_psrp: Callable = check_psrp
    check_ssh: Callable = check_ssh
    remove_setup_account: Callable = remove_setup_account
    run_checks: Callable = run_checks
    provision: Callable = provision


def step_check(lab: Lab, store: TemplateStore, probes: Probes) -> None:
    failed = [c for c in probes.run_checks(lab.runner, lab.settings, need_packer=False, need_ansible=True) if not c.ok]
    if failed:
        raise GoadError('host checks failed: ' + '; '.join(f'{c.name}: {c.detail}' for c in failed))
    templates = {}
    for os_name in lab.definition.templates_needed():
        template = store.latest(os_name)
        if template is None:
            raise GoadError(f'no {os_name} template: run goad template build {os_name}')
        templates[os_name] = template
    hosts: Dict[str, HostState] = {}
    for name, host in lab.definition.hosts.items():
        ip = lab.definition.ip(name, lab.state.ip_range)
        if probes.is_up(ip):
            raise GoadError(f'{ip} ({name}) already answers')
        hosts[name] = HostState(vmx=vm_path(lab.settings, name), template=templates[host.os].name,
                                hostname=host.hostname, ip=ip)
    lab.state.hosts = hosts
    lab.state.templates = sorted({h.template for h in hosts.values()})


def step_clone(lab: Lab, store: TemplateStore) -> None:
    def clone(name: str, host: HostState) -> None:
        if to_wsl(host.vmx).exists():
            return  # cloned by an earlier run
        lab.vmrun.clone_linked(store.windows_vmx(host.template), host.vmx, 'base', f'{lab.state.lab}-{name}')

    run_parallel(lab.state.hosts, clone, 'clone').raise_if_failed('clone')


def step_configure(lab: Lab) -> None:
    for name, host in lab.state.hosts.items():
        definition = lab.definition.hosts[name]
        vmx = Vmx.load(to_wsl(host.vmx))
        mac = lab_mac(host.ip)
        configure_hardware(vmx, definition.cpus, definition.memory, lab.settings.vmnet, mac)
        write_guestinfo(vmx, GuestConfig(hostname=host.hostname, ip=host.ip, prefix=24, gateway=None,
                                         dns=lab.definition.dns(name, lab.state.ip_range),
                                         admin_password=lab.definition.password, lab_mac=mac),
                        definition.family)
        vmx.save()


def _already_booted(lab: Lab, probes: Probes, name: str, host: HostState) -> bool:
    """True when the host answers and passes its check: first boot finished in an earlier run.
    The in-guest marker does not survive a power cycle, so the marker alone cannot tell."""
    family = lab.family(name)
    try:
        probes.wait_port(host.ip, port_for(family), PROBE_TIMEOUT)
        if family == 'windows':
            probes.check_psrp(host.ip, 'Administrator', lab.definition.password, host.hostname)
        else:
            probes.check_ssh(host.ip)
    except Exception:
        return False
    return True


def step_firstboot(lab: Lab, probes: Probes) -> None:
    pending = {name: host for name, host in lab.state.hosts.items() if not host.ready}
    start_all(lab.vmrun, lab.vms())   # ready hosts too: later steps need every VM running

    def boot(name: str, host: HostState) -> None:
        family = lab.family(name)
        deadline = time.monotonic() + FIRSTBOOT_TIMEOUT
        while True:
            marker = probes.firstboot_marker(lab.vmrun, host.vmx)
            if marker == FIRSTBOOT_DONE:
                break
            if marker.startswith(FIRSTBOOT_FAILED):
                raise GoadError(f'first boot {marker}')
            if _already_booted(lab, probes, name, host):   # marker is lost on a power cycle
                if family == 'windows':
                    probes.remove_setup_account(host.ip, lab.definition.password)   # idempotent
                return
            if time.monotonic() >= deadline:
                raise GoadError(f'first boot did not finish in {FIRSTBOOT_TIMEOUT:.0f}s')
            probes.sleep(FIRSTBOOT_POLL)
        probes.wait_port(host.ip, port_for(family), READY_TIMEOUT)
        if family == 'windows':
            probes.check_psrp(host.ip, 'Administrator', lab.definition.password, host.hostname)
            probes.remove_setup_account(host.ip, lab.definition.password)
        else:
            probes.check_ssh(host.ip)

    result = run_parallel(pending, boot, 'first boot')
    for name in result.ok:
        lab.state.hosts[name].ready = True
    lab.save()  # partial success survives a failed run
    result.raise_if_failed('first boot')


def step_provision(lab: Lab, probes: Probes) -> None:
    start_all(lab.vmrun, lab.vms())   # a resumed deploy may find the lab powered off
    wait_ready(lab.endpoints(), wait=probes.wait_port)
    if not probes.provision(lab.settings, lab.runner, lab.definition, lab.state):
        console.print('no Ansible playbooks yet (ansible/site.yml): provisioning skipped')


def step_finish(lab: Lab, probes: Probes) -> None:
    vms = lab.vms()
    stop_all(lab.vmrun, vms)
    todo = {name: vmx for name, vmx in vms.items() if 'base' not in lab.vmrun.snapshots(vmx)}
    run_parallel(todo, lambda name, vmx: lab.vmrun.snapshot(vmx, 'base'), 'snapshot').raise_if_failed('snapshot')
    taken_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    lab.state.snapshots = [s for s in lab.state.snapshots if s.name != 'base']
    lab.state.snapshots.append(SnapshotRecord('base', taken_at, 'taken by deploy',
                                              working_lab_path(lab.settings).read_text()))
    lab.state.current = 'base'
    start_all(lab.vmrun, vms)
    wait_ready(lab.endpoints(), wait=probes.wait_port)   # deploy returns a usable lab, like lab start/reset


def _open(lab_name: str, settings: Settings, ip_range: Optional[str]) -> LabState:
    state = load_state(settings)
    if state is not None:
        if state.deployed or state.lab != lab_name:
            raise GoadError(f'lab {state.lab} is already deployed: goad lab destroy first')
        if ip_range and ip_range != state.ip_range:
            raise GoadError(f'lab {lab_name} was started with --range {state.ip_range}')
        return state
    source = shipped_lab(lab_name)
    for host in load_lab(source).hosts:
        folder = vm_folder(settings, host)
        if to_wsl(folder).exists():
            raise GoadError(f'leftover VM folder {folder}: delete it or run goad lab destroy')
    working = working_lab_path(settings)
    working.parent.mkdir(parents=True, exist_ok=True)
    working.write_text(source.read_text())
    return LabState(lab=lab_name, ip_range=ip_range or settings.ip_range)


def deploy(lab_name: str, settings: Settings, runner, store: TemplateStore, ip_range: Optional[str] = None,
           probes: Optional[Probes] = None) -> LabState:
    probes = probes or Probes()
    state = _open(lab_name, settings, ip_range)
    lab = Lab(settings, runner, Vmrun(runner, settings), state, load_lab(working_lab_path(settings)))
    step_functions: Dict[str, Callable[[Lab], None]] = {
        'check': lambda l: step_check(l, store, probes),
        'clone': lambda l: step_clone(l, store),
        'configure': step_configure,
        'firstboot': lambda l: step_firstboot(l, probes),
        'provision': lambda l: step_provision(l, probes),
        'finish': lambda l: step_finish(l, probes),
    }
    finished = STEPS.index(state.step) + 1 if state.step else 0
    for step in STEPS[finished:]:
        if step not in step_functions:
            break
        console.print(f'[bold]{step}[/bold]')
        start = time.monotonic()
        try:
            step_functions[step](lab)
        except GoadError:
            lab.save()
            raise
        state.durations[step] = round(time.monotonic() - start, 1)
        state.step = step
        lab.save()
    _print_durations(state)
    return state


def _print_durations(state: LabState) -> None:
    table = Table('Step', 'Seconds')
    for step in STEPS:
        if step in state.durations:
            table.add_row(step, f'{state.durations[step]:.0f}')
    table.add_row('Total', f'{sum(state.durations.values()):.0f}')
    console.print(table)
