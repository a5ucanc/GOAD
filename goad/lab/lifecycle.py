"""Lab status, destroy, credentials and single-VM control."""
import shutil
from dataclasses import dataclass
from typing import List

from goad import GoadError
from goad.host.paths import to_wsl
from goad.lab.context import Lab, vm_folder
from goad.lab.power import start_all, stop_all
from goad.settings import Settings
from goad.state import delete_state, load_state
from goad.vmware.parallel import run_parallel
from goad.vmware.vmrun import Vmrun, VmrunError, norm_vmx


@dataclass
class HostStatus:
    host: str
    hostname: str
    ip: str
    template: str
    power: str


@dataclass
class Credential:
    account: str
    password: str
    scope: str


def status(lab: Lab) -> List[HostStatus]:
    up = set(lab.vmrun.running())
    return [HostStatus(name, host.hostname, host.ip, host.template,
                       'running' if norm_vmx(host.vmx) in up else 'off')
            for name, host in lab.state.hosts.items()]


def destroy(settings: Settings, runner, yes: bool) -> None:
    from goad.cli import confirm
    state = load_state(settings)
    if state is None:
        raise GoadError('no lab deployed')
    if not confirm(f'Destroy lab {state.lab} and delete its VMs?', yes):
        raise GoadError('cancelled')
    vmrun = Vmrun(runner, settings)
    vms = {name: host.vmx for name, host in state.hosts.items()}
    try:
        stop_all(vmrun, vms, hard=True)
    except GoadError:
        pass

    def delete(name: str, vmx: str) -> None:
        try:
            vmrun.delete_vm(vmx)
        except VmrunError:
            pass

    run_parallel(vms, delete, 'delete')
    failed = []
    for name in vms:
        folder = to_wsl(vm_folder(settings, name))
        if folder.exists():
            try:
                shutil.rmtree(folder)
            except OSError as exc:
                failed.append(f'{folder} ({exc})')
    if failed:
        raise GoadError(f'cannot remove {"; ".join(failed)}: close VMware and retry')
    delete_state(settings)


def creds(lab: Lab) -> List[Credential]:
    password = lab.definition.password
    rows = [Credential(f'{d.netbios}\\Administrator', password, f'domain {d.name}')
            for d in lab.definition.domains.values()]
    for name in lab.state.hosts:
        if lab.family(name) == 'windows':
            rows.append(Credential('.\\Administrator', password, f'local {name}'))
        else:
            rows.append(Credential('goad', password, f'ssh {name}'))
    return rows


def _vmx(lab: Lab, host: str) -> str:
    vms = lab.vms()
    if host not in vms:
        raise GoadError(f'no VM named {host}: see goad lab status')
    return vms[host]


def vm_start(lab: Lab, host: str) -> None:
    start_all(lab.vmrun, {host: _vmx(lab, host)})


def vm_stop(lab: Lab, host: str, hard: bool = False) -> None:
    stop_all(lab.vmrun, {host: _vmx(lab, host)}, hard=hard)


def vm_console(lab: Lab, host: str) -> None:
    vmx = _vmx(lab, host)
    lab.runner.spawn([str(to_wsl(lab.settings.vmware_dir) / 'vmware.exe'), vmx])
