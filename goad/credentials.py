import os
from typing import List, Optional, Tuple

import yaml

# (scope, account, password, kind)
CredentialRow = Tuple[str, str, str, str]


def _scenario_account(scenarios_path: str, name: str) -> Optional[Tuple[str, str]]:
    vars_file = os.path.join(scenarios_path, name, 'data', 'vars.yml')
    try:
        with open(vars_file, 'r') as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict) or 'user' not in data or 'password' not in data:
        return None
    return str(data['user']), str(data['password'])


def collect_credentials(lab: dict, enabled_scenarios: List[Tuple[str, str]],
                        scenarios_path: Optional[str]) -> List[CredentialRow]:
    """
    List every known credential of a lab config (the `lab` object of config.json).
    :param enabled_scenarios: (scenario name, target host key) pairs; accounts created by them are added
    :param scenarios_path: <project>/scenarios, or None to skip scenario accounts
    """
    rows = []
    hosts = lab.get('hosts', {}) or {}
    domains = lab.get('domains', {}) or {}

    for domain, d in domains.items():
        netbios = d.get('netbios_name', domain.split('.')[0].upper())
        if 'domain_password' in d:
            rows.append((domain, f'{netbios}\\Administrator', d['domain_password'], 'domain admin'))
        for user, u in sorted((d.get('users', {}) or {}).items()):
            if 'password' in u:
                rows.append((domain, f'{netbios}\\{user}', u['password'], 'user'))

    for host_key, h in hosts.items():
        scope = f"{host_key} ({h['hostname']})" if 'hostname' in h else host_key
        if 'local_admin_password' in h:
            rows.append((scope, '.\\Administrator', h['local_admin_password'], 'local admin'))
        mssql = h.get('mssql') or {}
        if 'sa_password' in mssql:
            rows.append((scope, 'sa', mssql['sa_password'], 'mssql'))

    if scenarios_path:
        for name, target in enabled_scenarios:
            account = _scenario_account(scenarios_path, name)
            domain = (hosts.get(target) or {}).get('domain')
            if account is None or domain is None:
                continue
            netbios = (domains.get(domain) or {}).get('netbios_name', domain.split('.')[0].upper())
            rows.append((domain, f'{netbios}\\{account[0]}', account[1], f'scenario {name}'))
    return rows
