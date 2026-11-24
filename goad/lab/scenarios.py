"""Scenario catalogue: scenarios/<name>.yml fragments, target kinds and placeholder substitution."""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from goad import GoadError
from goad.lab.definition import REPO, SERVICES

SCENARIO_DIR = REPO / 'scenarios'
KINDS = ('domain', 'server', 'ca', 'trust')
_KEYS = {'description', 'target', 'fragment', 'requires'}


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    kind: str
    fragment: Dict[str, Any]
    requires: Optional[str] = None


def is_kind(kind: Any) -> bool:
    return kind in KINDS or (isinstance(kind, str) and kind.startswith('service:') and kind[len('service:'):] in SERVICES)


def load_catalogue(directory: Optional[Path] = None) -> Dict[str, Scenario]:
    """Every scenarios/*.yml file; the directory is read at call time so tests can point it elsewhere."""
    directory = SCENARIO_DIR if directory is None else directory
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
            raise GoadError(f'{path.name}: unknown keys {extra}; allowed: description, target, fragment, requires')
        if not is_kind(data.get('target')):
            kinds = list(KINDS) + [f'service:{s}' for s in SERVICES]
            raise GoadError(f'{path.name}: target must be one of {kinds}, got {data.get("target")!r}')
        requires = data.get('requires')
        if requires is not None and not isinstance(requires, str):
            raise GoadError(f'{path.name}: requires must be an extension name')
        if not isinstance(data.get('fragment'), dict):
            raise GoadError(f'{path.name}: fragment must be a mapping')
        catalogue[path.stem] = Scenario(path.stem, str(data.get('description', '')), data['target'], data['fragment'], requires)
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
        if kind.startswith('service:'):
            ok = kind[len('service:'):] in (h.get('services') or {})
        elif kind == 'domain':
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
    if kind.startswith('service:') and 'srv02' in out:
        out.remove('srv02')
        out.insert(0, 'srv02')
    return out


def check_requires(scenario: 'Scenario', raw: Dict[str, Any], source: str) -> None:
    from goad.lab import extensions  # function-local: extensions imports this module
    req = scenario.requires
    if req and req not in extensions.entries(raw):
        raise GoadError(f'{source}: scenario {scenario.name} needs extension {req}: run goad extension add {req}')


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
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)) or a != b or type(a) is not type(b):
        raise GoadError(f'conflict: keys substituting to one key give different values {a!r} and {b!r}')
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
        elif (old == value and type(old) is type(value)) or ('settings' in _path and str(old) == str(value)):
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
                raise GoadError(f'{source}: {who} sets {dotted} to {value!r}, {owner} set it to {old!r}')
            raise GoadError(f'{source}: {who} sets {dotted}, already set by {owner or "lab.yml"}')


def _union(base: List[Any], items: List[Any]) -> None:
    for item in items:
        if item not in base:
            base.append(copy.deepcopy(item))


def expand(raw: Dict[str, Any], source: str, catalogue: Optional[Dict[str, Scenario]] = None) -> Dict[str, Any]:
    from goad.lab import extensions  # extensions imports this module at call time: function-local avoids the cycle
    # raw is the lab as written: extension fragments (hosts, services) merge in before any scenario is checked
    raw = extensions.expand(raw, source)
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
        check_requires(scenario, raw, source)
        valid = valid_targets(raw, scenario.kind)
        if target not in valid:
            choice = f'choose one of {valid}' if valid else 'none in this lab'
            raise GoadError(f'{source}: scenario {name} needs a {scenario.kind} target: {choice}')
        entry_id = f'{name}@{target}'
        if entry_id in seen:
            raise GoadError(f'{source}: duplicate entry {entry_id}')
        seen.add(entry_id)
        who = f'scenario {entry_id}'
        fragment = substitute(scenario.fragment, placeholders(raw, target))
        merge_fragment(result, fragment, owners, who, source)
    return result
