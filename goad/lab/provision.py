"""Provision: check the working lab.yml against the deployed hosts, then run ansible-playbook."""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from goad import GoadError
from goad.host.runner import Runner
from goad.lab.definition import REPO, LabDef
from goad.lab.inventory import write_inventory
from goad.settings import Settings
from goad.state import LabState, log_dir

PLAYBOOK = REPO / 'ansible' / 'site.yml'
_TAIL = 'destroy and redeploy to change hosts'


def check_compatible(lab: LabDef, state: LabState) -> None:
    for name in state.hosts:
        if name not in lab.hosts:
            raise GoadError(f'host {name} was removed from lab.yml: {_TAIL}')
    for name, h in lab.hosts.items():
        deployed = state.hosts.get(name)
        if deployed is None:
            raise GoadError(f'host {name} was added to lab.yml: {_TAIL}')
        if h.hostname != deployed.hostname:
            raise GoadError(f'host {name}: hostname changed from {deployed.hostname} to {h.hostname}: {_TAIL}')
        ip = lab.ip(name, state.ip_range)
        if ip != deployed.ip:
            raise GoadError(f'host {name}: ip changed from {deployed.ip} to {ip}: {_TAIL}')
        deployed_os = deployed.template.rsplit('-v', 1)[0]
        if h.os != deployed_os:
            raise GoadError(f'host {name}: os changed from {deployed_os} to {h.os}: {_TAIL}')


def provision(settings: Settings, runner: Runner, lab: LabDef, state: LabState,
              tags: Optional[List[str]] = None, playbook: Path = PLAYBOOK) -> bool:
    if not playbook.exists():
        return False
    check_compatible(lab, state)
    inventory = write_inventory(settings, lab, state.ip_range)
    argv = ['ansible-playbook', '-i', str(inventory), '-f', str(len(lab.hosts)), str(playbook)]
    if tags:
        argv += ['--tags', ','.join(tags)]
    log = log_dir(settings) / f'provision-{datetime.now().strftime("%Y%m%d-%H%M%S")}.log'
    code = runner.stream(argv, log)
    if code != 0:
        raise GoadError(f'ansible-playbook failed (exit {code}): see {log}')
    return True
