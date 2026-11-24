"""Extension catalogue: extensions/<name>.yml per-lab fragments listed under extensions: in lab.yml."""
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from goad import GoadError
from goad.lab.definition import REPO

EXTENSION_DIR = REPO / 'extensions'
_KEYS = {'description', 'labs', 'credentials'}
_CREDENTIAL_KEYS = {'account', 'password', 'scope'}


@dataclass(frozen=True)
class Extension:
    name: str
    description: str
    labs: Dict[str, Dict[str, Any]]
    # (account, password, scope); scope may contain {range}
    credentials: Tuple[Tuple[str, str, str], ...]


def _credentials(value: Any, source: str) -> Tuple[Tuple[str, str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
            isinstance(c, dict) and set(c) == _CREDENTIAL_KEYS and all(isinstance(v, str) for v in c.values())
            for c in value):
        raise GoadError(f'{source}: credentials must be a list of mappings with exactly the keys account, password and scope')
    return tuple((c['account'], c['password'], c['scope']) for c in value)


def load_catalogue(directory: Optional[Path] = None) -> Dict[str, Extension]:
    """Every extensions/*.yml file; the directory is read at call time so tests can point it elsewhere."""
    directory = Path(EXTENSION_DIR if directory is None else directory)
    catalogue: Dict[str, Extension] = {}
    for path in sorted(directory.glob('*.yml')):
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
        except yaml.YAMLError as e:
            raise GoadError(f'{path.name}: invalid YAML: {e}')
        if not isinstance(data, dict):
            raise GoadError(f'{path.name}: extension file must be a mapping')
        extra = sorted(set(data) - _KEYS)
        if extra:
            raise GoadError(f'{path.name}: unknown keys {extra}; allowed: description, labs, credentials')
        labs = data.get('labs')
        if not isinstance(labs, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in labs.items()):
            raise GoadError(f'{path.name}: labs must be a mapping of lab name to fragment mapping')
        catalogue[path.stem] = Extension(path.stem, str(data.get('description', '')), labs,
                                         _credentials(data.get('credentials'), path.name))
    return catalogue


def entries(raw: Dict[str, Any]) -> List[str]:
    """The extensions: list of a lab definition; absent or null is empty."""
    value = raw.get('extensions')
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value) or len(set(value)) != len(value):
        raise GoadError('extensions must be a list of unique extension names')
    return list(value)


def _fragment(catalogue: Dict[str, Extension], name: str, lab: Any, source: str) -> Dict[str, Any]:
    ext = catalogue.get(name)
    if ext is None or lab not in ext.labs:
        raise GoadError(f'{source}: extension {name} does not apply to lab {lab}')
    return ext.labs[lab]


def expand(raw: Dict[str, Any], source: str, catalogue: Optional[Dict[str, Extension]] = None) -> Dict[str, Any]:
    """raw with each listed extension's fragment for this lab merged in, in list order."""
    from goad.lab import scenarios  # scenarios imports definition, which imports this module lazily
    result = copy.deepcopy(raw)
    try:
        names = entries(raw)
    except GoadError as e:
        raise GoadError(f'{source}: {e}')
    if not names:
        return result
    if catalogue is None:
        catalogue = load_catalogue()
    lab = raw.get('name')
    owners: Dict[Tuple[str, ...], str] = {}
    for name in names:
        scenarios.merge_fragment(result, _fragment(catalogue, name, lab, source), owners,
                                 f'extension {name}', source)
    return result


def extension_hosts(raw: Dict[str, Any], name: str, catalogue: Optional[Dict[str, Extension]] = None) -> List[str]:
    """Host keys the fragment of extension name adds that neither raw (before expansion) nor another listed
    extension declares: the hosts that come and go with it."""
    if catalogue is None:
        catalogue = load_catalogue()
    lab = raw.get('name')
    source = 'lab definition'
    hosts = (_fragment(catalogue, name, lab, source).get('hosts') or {})
    taken = set(raw.get('hosts') or {})
    for other in entries(raw):
        if other != name:
            taken |= set(_fragment(catalogue, other, lab, source).get('hosts') or {})
    return [h for h in hosts if h not in taken]
