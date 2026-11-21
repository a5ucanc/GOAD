"""Lab deploy: ordered, resumable steps. Each finished step is saved in lab.json."""
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from rich.console import Console
from rich.table import Table

from goad import GoadError
from goad.host.checks import run_checks
from goad.host.paths import to_wsl
from goad.lab.context import Lab, vm_folder, vm_path
from goad.lab.definition import load_lab, shipped_lab
from goad.lab.provision import provision
from goad.lab.remote import remove_setup_account
from goad.settings import Settings
from goad.state import STEPS, HostState, LabState, load_state, save_state, working_lab_path
from goad.templates.smoke import check_psrp, check_ssh, is_up, wait_firstboot, wait_port
from goad.templates.store import TemplateStore
from goad.vmware.guestinfo import GuestConfig, configure_hardware, lab_mac, write_guestinfo
from goad.vmware.parallel import run_parallel
from goad.vmware.vmrun import Vmrun
from goad.vmware.vmx import Vmx

console = Console()


@dataclass
class Probes:
    """Network and host probes, replaceable in tests."""
    is_up: Callable = is_up
    wait_firstboot: Callable = wait_firstboot
    wait_port: Callable = wait_port
    check_psrp: Callable = check_psrp
    check_ssh: Callable = check_ssh
    remove_setup_account: Callable = remove_setup_account
    run_checks: Callable = run_checks
    provision: Callable = provision


def step_check(lab: Lab, store: TemplateStore, probes: Probes) -> None:
    failed = [c for c in probes.run_checks(lab.runner, lab.settings, need_packer=False) if not c.ok]
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
    # Task 6 adds firstboot, provision and finish here
    step_functions: Dict[str, Callable[[Lab], None]] = {
        'check': lambda l: step_check(l, store, probes),
        'clone': lambda l: step_clone(l, store),
        'configure': step_configure,
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
