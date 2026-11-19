import copy
import json
import os
from typing import Iterable, List, Optional, Tuple

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


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _merge(base: dict, extra: dict) -> dict:
    """Recursive dict merge, like ansible combine(recursive=True) used by the extension playbooks."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _extension_service_rows(info: dict, ip_range: Optional[str]) -> List[CredentialRow]:
    rows = []
    for c in info.get('credentials', []) or []:
        if not all(k in c for k in ('scope', 'account', 'password', 'kind')):
            continue
        scope = c['scope'].replace('{{ip_range}}', ip_range) if ip_range else c['scope']
        rows.append((scope, c['account'], c['password'], c['kind']))
    return rows


def collect_credentials(lab: dict, enabled_scenarios: List[Tuple[str, str]],
                        scenarios_path: Optional[str], extensions_path: Optional[str] = None,
                        enabled_extensions: Iterable[str] = (), ip_range: Optional[str] = None) -> List[CredentialRow]:
    """
    List every known credential of a lab config (the `lab` object of config.json).
    :param enabled_scenarios: (scenario name, target host key) pairs; accounts created by them are added
    :param scenarios_path: <project>/scenarios, or None to skip scenario accounts
    :param extensions_path: <project>/extensions, or None to skip extension accounts
    :param enabled_extensions: extensions installed on the instance. Their data/config.json lab_extension
        (hosts, users) is merged into the lab, and their extension.json "credentials" are added.
    :param ip_range: instance ip range, replaces {{ip_range}} in the extension credentials scope
    """
    service_rows = []
    if extensions_path:
        lab = copy.deepcopy(lab)
        for name in enabled_extensions:
            data = _read_json(os.path.join(extensions_path, name, 'data', 'config.json')) or {}
            if isinstance(data.get('lab_extension'), dict):
                _merge(lab, data['lab_extension'])
            info = _read_json(os.path.join(extensions_path, name, 'extension.json')) or {}
            service_rows += _extension_service_rows(info, ip_range)

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
        # linux hosts (lx01) carry the field for cloud images only, no Administrator account exists
        if 'local_admin_password' in h and h.get('os') != 'linux':
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
    return rows + service_rows
