"""Lab context: settings, runner, vmrun, state and definition of the deployed lab."""
from dataclasses import dataclass
from typing import Dict, Tuple

from goad import GoadError
from goad.host.runner import Runner
from goad.lab.definition import LabDef, load_lab
from goad.lab.power import port_for
from goad.settings import Settings
from goad.state import LabState, load_state, save_state, working_lab_path
from goad.vmware.vmrun import Vmrun


def vm_folder(settings: Settings, host: str) -> str:
    return f'{settings.lab_root}\\{host}'


def vm_path(settings: Settings, host: str) -> str:
    return f'{vm_folder(settings, host)}\\{host}.vmx'


@dataclass
class Lab:
    settings: Settings
    runner: Runner
    vmrun: Vmrun
    state: LabState
    definition: LabDef

    def vms(self) -> Dict[str, str]:
        return {name: host.vmx for name, host in self.state.hosts.items()}

    def endpoints(self) -> Dict[str, Tuple[str, int]]:
        return {name: (host.ip, port_for(self.definition.hosts[name].family))
                for name, host in self.state.hosts.items()}

    def save(self) -> None:
        save_state(self.settings, self.state)


def open_lab(settings: Settings, runner: Runner) -> Lab:
    state = load_state(settings)
    if state is None:
        raise GoadError('no lab deployed: run goad lab deploy <lab>')
    return Lab(settings, runner, Vmrun(runner, settings), state, load_lab(working_lab_path(settings)))
