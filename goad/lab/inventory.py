"""Ansible inventory generated from a lab definition."""
from pathlib import Path
from typing import Any, Dict

import yaml

from goad.lab.definition import LabDef
from goad.settings import Settings
from goad.state import inventory_path


def render_inventory(lab: LabDef, ip_range: str) -> Dict[str, Any]:
    def entry(name: str) -> Dict[str, Any]:
        h = lab.hosts[name]
        return {'ansible_host': lab.ip(name, ip_range), 'hostname': h.hostname, 'domain': h.domain}

    def group(members: list) -> Dict[str, Any]:
        return {'hosts': {name: entry(name) for name in members}}

    names = list(lab.hosts)
    windows = [n for n in names if lab.hosts[n].family == 'windows']
    linux = [n for n in names if lab.hosts[n].family == 'linux']
    children: Dict[str, Any] = {
        'windows': {**group(windows), 'vars': {'ansible_connection': 'psrp', 'ansible_psrp_auth': 'ntlm',
                                               'ansible_psrp_protocol': 'http'}},
        'linux': {**group(linux), 'vars': {'ansible_connection': 'ssh', 'ansible_user': 'goad'}},
    }
    for role in ('dc', 'server', 'workstation'):
        children[role] = group([n for n in names if lab.hosts[n].role == role])
    return {'all': {
        'vars': {'ansible_user': 'Administrator', 'ansible_password': lab.password, 'lab_name': lab.name,
                 'dns_forwarder': lab.dns_forwarder},
        'children': children}}


def write_inventory(settings: Settings, lab: LabDef, ip_range: str) -> Path:
    path = inventory_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(render_inventory(lab, ip_range), sort_keys=False))
    return path
