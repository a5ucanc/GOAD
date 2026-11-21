"""Lab context: settings, runner, vmrun, state and definition of the deployed lab."""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from goad import GoadError
from goad.host.runner import Runner
from goad.lab.definition import LabDef, load_lab, parse_lab
from goad.lab.power import port_for
from goad.settings import Settings
from goad.state import LabState, load_state, save_state, working_lab_path
from goad.templates.store import OS_FAMILY
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
    definition: Optional[LabDef]   # None when opened without the working lab.yml

    def vms(self) -> Dict[str, str]:
        return {name: host.vmx for name, host in self.state.hosts.items()}

    def family(self, host: str) -> str:
        """OS family of a deployed host, from its template name (<os>-v<N>) in the state, not from lab.yml."""
        return OS_FAMILY[self.state.hosts[host].template.rsplit('-v', 1)[0]]

    def endpoints(self) -> Dict[str, Tuple[str, int]]:
        return {name: (host.ip, port_for(self.family(name))) for name, host in self.state.hosts.items()}

    def save(self) -> None:
        save_state(self.settings, self.state)


def open_lab(settings: Settings, runner: Runner, lab_yml: Optional[str] = None,
             need_definition: bool = True) -> Lab:
    """Open the deployed lab. With lab_yml, the definition comes from that text, not the working lab.yml.
    With need_definition=False and no lab_yml, the working lab.yml is not read and the definition is None."""
    state = load_state(settings)
    if state is None:
        raise GoadError('no lab deployed: run goad lab deploy <lab>')
    if lab_yml is not None:
        definition = parse_lab(lab_yml, 'snapshot lab.yml')
    elif need_definition:
        definition = load_lab(working_lab_path(settings))
    else:
        definition = None
    return Lab(settings, runner, Vmrun(runner, settings), state, definition)
