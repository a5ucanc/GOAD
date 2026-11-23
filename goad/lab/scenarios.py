"""Scenario catalogue: scenarios/<name>.yml fragments, target kinds and placeholder substitution."""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
        except yaml.YAMLError as e:
            raise GoadError(f'{path.name}: invalid YAML: {e}')
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


def _merge_values(a: Any, b: Any) -> Any:
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge_values(out[k], v) if k in out else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        return a + [v for v in b if v not in a]
    return b


def substitute(value: Any, values: Dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, repl in values.items():
            value = value.replace(key, repl)
        return value
    if isinstance(value, dict):
        out: Dict[Any, Any] = {}
        for k, v in value.items():
            k, v = substitute(k, values), substitute(v, values)
            # two keys can substitute to one ({target} and {dc} on a CA that is the DC): merge, never overwrite
            out[k] = _merge_values(out[k], v) if k in out else v
        return out
    if isinstance(value, list):
        return [substitute(v, values) for v in value]
    return copy.deepcopy(value)


def merge_fragment(base: Dict[str, Any], fragment: Dict[str, Any], owners: Dict[Tuple[str, ...], str],
                   who: str, source: str, _path: Tuple[str, ...] = ()) -> None:
    for key, value in fragment.items():
        path = _path + (key,)
        if key not in base:
            if isinstance(value, dict):
                base[key] = {}
                merge_fragment(base[key], value, owners, who, source, path)
            elif isinstance(value, list):
                base[key] = []
                _union(base[key], value)
            else:
                base[key] = copy.deepcopy(value)
                owners[path] = who
            continue
        old = base[key]
        if isinstance(old, dict) and isinstance(value, dict):
            merge_fragment(old, value, owners, who, source, path)
        elif isinstance(old, list) and isinstance(value, list):
            _union(old, value)
        elif old == value and type(old) is type(value):
            if 'settings' in _path:
                owners.setdefault(path, who)
            continue
        else:
            dotted = '.'.join(path)
            owner = owners.get(path)
            if 'settings' in _path:
                if owner is None:
                    base[key] = copy.deepcopy(value)
                    owners[path] = who
                    continue
                raise GoadError(f'{source}: scenario {who} sets {dotted} to {value!r}, scenario {owner} set it to {old!r}')
            raise GoadError(f'{source}: scenario {who} sets {dotted}, already set by {owner or "lab.yml"}')


def _union(base: List[Any], items: List[Any]) -> None:
    for item in items:
        if item not in base:
            base.append(copy.deepcopy(item))


def expand(raw: Dict[str, Any], source: str, catalogue: Optional[Dict[str, Scenario]] = None) -> Dict[str, Any]:
    result = copy.deepcopy(raw)
    entries = result.get('scenarios')
    if entries is None or entries == []:
        return result
    if not isinstance(entries, list) or not all(isinstance(e, dict) and set(e) == {'name', 'target'}
                                           and isinstance(e['name'], str) and isinstance(e['target'], str) for e in entries):
        raise GoadError(f'{source}: scenarios must be a list of mappings with exactly the keys name and target')
    if catalogue is None:
        catalogue = load_catalogue()
    owners: Dict[Tuple[str, ...], str] = {}
    seen = set()
    hosts = raw.get('hosts') or {}
    for entry in entries:
        name, target = entry['name'], entry['target']
        if name not in catalogue:
            raise GoadError(f'{source}: unknown scenario {name!r}')
        if target not in hosts:
            raise GoadError(f'{source}: unknown host {target!r} in scenario {name}')
        scenario = catalogue[name]
        valid = valid_targets(raw, scenario.kind)
        if target not in valid:
            choice = f'choose one of {valid}' if valid else 'none in this lab'
            raise GoadError(f'{source}: scenario {name} needs a {scenario.kind} target: {choice}')
        who = f'{name}@{target}'
        if who in seen:
            raise GoadError(f'{source}: duplicate entry {who}')
        seen.add(who)
        fragment = substitute(scenario.fragment, placeholders(raw, target))
        merge_fragment(result, fragment, owners, who, source)
    return result
