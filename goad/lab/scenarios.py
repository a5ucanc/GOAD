"""Scenario catalogue: scenarios/<name>.yml fragments, target kinds and placeholder substitution."""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from goad import GoadError
from goad.lab.definition import REPO

SCENARIO_DIR = REPO / 'scenarios'
KINDS = ('domain', 'server', 'ca', 'trust')
_KEYS = {'description', 'target', 'fragment'}


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    kind: str
    fragment: Dict[str, Any]


def load_catalogue(directory: Path = SCENARIO_DIR) -> Dict[str, Scenario]:
    catalogue: Dict[str, Scenario] = {}
    for path in sorted(Path(directory).glob('*.yml')):
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise GoadError(f'{path.name}: scenario file must be a mapping')
        extra = sorted(set(data) - _KEYS)
        if extra:
            raise GoadError(f'{path.name}: unknown keys {extra}; allowed: description, target, fragment')
        if data.get('target') not in KINDS:
            raise GoadError(f'{path.name}: target must be one of {list(KINDS)}, got {data.get("target")!r}')
        if not isinstance(data.get('fragment'), dict):
            raise GoadError(f'{path.name}: fragment must be a mapping')
        catalogue[path.stem] = Scenario(path.stem, str(data.get('description', '')), data['target'], data['fragment'])
    return catalogue


def _trust_domains(raw: Dict[str, Any]) -> set:
    domains = raw.get('domains') or {}
    named = {d['trust'] for d in domains.values() if d.get('trust')}
    return {n for n, d in domains.items() if not d.get('parent') and (d.get('trust') or n in named)}


def valid_targets(raw: Dict[str, Any], kind: str) -> List[str]:
    hosts = raw.get('hosts') or {}
    trusted = _trust_domains(raw) if kind == 'trust' else set()
    out = []
    for key, h in hosts.items():
        if kind == 'domain':
            ok = h.get('role') == 'dc'
        elif kind == 'server':
            ok = h.get('role') == 'server' and bool(h.get('domain'))
        elif kind == 'ca':
            ok = h.get('ca') is True
        elif kind == 'trust':
            ok = h.get('role') == 'dc' and h.get('domain') in trusted
        else:
            ok = False
        if ok:
            out.append(key)
    return out


def placeholders(raw: Dict[str, Any], target: str) -> Dict[str, str]:
    hosts = raw.get('hosts') or {}
    domains = raw.get('domains') or {}
    host = hosts.get(target) or {}
    domain = host.get('domain', '')
    info = domains.get(domain) or {}
    dc = info.get('dc', '')
    dc_hostname = (hosts.get(dc) or {}).get('hostname', '')
    values = {
        '{target}': target,
        '{target_hostname}': host.get('hostname', ''),
        '{domain}': domain,
        '{netbios}': info.get('netbios', ''),
        '{dc}': dc,
        '{dc_hostname}': dc_hostname,
        '{dc_fqdn}': f'{dc_hostname}.{domain}',
    }
    if domain in _trust_domains(raw):
        if info.get('trust'):
            values['{other_forest}'] = info['trust']
        else:
            values['{other_forest}'] = next((n for n, d in domains.items() if d.get('trust') == domain), '')
    return values


def substitute(value: Any, values: Dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, repl in values.items():
            value = value.replace(key, repl)
        return value
    if isinstance(value, dict):
        return {substitute(k, values): substitute(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, values) for v in value]
    return copy.deepcopy(value)
