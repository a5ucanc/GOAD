"""goad scenario enable, disable and list: edit the scenarios list of the working lab.yml, then provision or reset."""
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from goad import GoadError
from goad.lab import scenarios
from goad.lab.definition import parse_lab
from goad.state import LabState, load_state, working_lab_path

# Plays that carry every scenario primitive: 'join and content' and 'foreign members' (content),
# 'post-join' (local_groups), 'settings' (settings; adcs runs inside content and settings).
ENABLE_TAGS = ['content', 'local_groups', 'settings']
SOURCE = 'lab.yml'


def _load(text: str) -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GoadError(f'{SOURCE}: invalid YAML: {e}')
    if not isinstance(raw, dict):
        raise GoadError(f'{SOURCE}: must be a mapping')
    return raw


def _dump(raw: Dict[str, Any]) -> str:
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def _entries(raw: Dict[str, Any]) -> List[Dict[str, str]]:
    entries = raw.get('scenarios') or []
    if not isinstance(entries, list) or not all(isinstance(e, dict) and set(e) == {'name', 'target'}
                                               and isinstance(e['name'], str) and isinstance(e['target'], str)
                                               for e in entries):
        raise GoadError(f'{SOURCE}: scenarios must be a list of mappings with exactly the keys name and target')
    return list(entries)


def add_entry(text: str, name: str, target: Optional[str]) -> Tuple[str, str]:
    raw = _load(text)
    catalogue = scenarios.load_catalogue()
    if name not in catalogue:
        raise GoadError(f'unknown scenario {name}: see goad scenario list')
    kind = catalogue[name].kind
    valid = scenarios.valid_targets(raw, kind)
    if target is None:
        if not valid:
            raise GoadError(f'scenario {name} needs a {kind} target: none in this lab')
        target = valid[0]
    elif target not in (raw.get('hosts') or {}):
        raise GoadError(f'unknown host {target}')
    elif target not in valid:
        choice = f'choose one of {valid}' if valid else 'none in this lab'
        raise GoadError(f'scenario {name} needs a {kind} target: {choice}')
    entries = _entries(raw)
    entry = {'name': name, 'target': target}
    if entry in entries:
        raise GoadError(f'scenario {name}@{target} is already enabled')
    raw['scenarios'] = entries + [entry]
    new_text = _dump(raw)
    parse_lab(new_text, SOURCE)
    return new_text, target


def remove_entry(text: str, name: str, target: Optional[str]) -> Tuple[str, str]:
    raw = _load(text)
    entries = _entries(raw)
    targets = [e['target'] for e in entries if e['name'] == name]
    if target is None:
        if len(targets) > 1:
            raise GoadError(f'scenario {name} is enabled on {", ".join(targets)}: pass --target')
        if targets:
            target = targets[0]
    if target not in targets:
        raise GoadError(f'scenario {name} is not enabled' + (f' on {target}' if target else ''))
    entries = [e for e in entries if not (e['name'] == name and e['target'] == target)]
    if entries:
        raw['scenarios'] = entries
    else:
        raw.pop('scenarios', None)
    new_text = _dump(raw)
    parse_lab(new_text, SOURCE)
    return new_text, target


def _strip_settings(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_settings(v) for k, v in value.items() if not (k == 'settings' and isinstance(v, dict))}
    if isinstance(value, list):
        return [_strip_settings(v) for v in value]
    return value


def _subset(old: Any, new: Any, path: str) -> Optional[str]:
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return path
        for key, value in old.items():
            sub = f'{path}.{key}' if path else str(key)
            if key not in new:
                return sub
            blocked = _subset(value, new[key], sub)
            if blocked:
                return blocked
        return None
    if isinstance(old, list):
        if not isinstance(new, list) or any(item not in new for item in old):
            return path
        return None
    return None if old == new and type(old) is type(new) else path


def contained(old_text: str, new_text: str) -> Optional[str]:
    """None when old's expanded content is contained in new's (setting values may differ), else the blocking path."""
    old_raw, new_raw = _load(old_text), _load(new_text)
    new_entries = _entries(new_raw)
    for entry in _entries(old_raw):
        if entry not in new_entries:
            return f'scenarios.{entry["name"]}@{entry["target"]}'
    old_exp = _strip_settings(scenarios.expand(old_raw, SOURCE))
    new_exp = _strip_settings(scenarios.expand(new_raw, SOURCE))
    old_exp.pop('scenarios', None)
    new_exp.pop('scenarios', None)
    blocked = _subset(old_exp, new_exp, '')
    if blocked:
        return blocked
    old_lab, new_lab = parse_lab(old_text, SOURCE), parse_lab(new_text, SOURCE)
    for host in old_lab.hosts:
        new_keys = new_lab.effective_settings(host)
        for key in old_lab.effective_settings(host):
            if key not in new_keys:
                return f'hosts.{host}.settings.{key}'
    return None


def pick_snapshot(state: LabState, new_text: str) -> str:
    from goad.lab.snapshots import unusable
    for record in reversed(state.snapshots):
        if unusable(record, new_text):
            continue
        try:
            if contained(record.lab_yml, new_text) is None:
                return record.name
        except GoadError:
            continue   # a record whose lab.yml no longer parses cannot be a reset target
    base = state.snapshot('base')
    if base is None:
        raise GoadError('no snapshot qualifies and there is no base snapshot: provision cannot remove content; redeploy')
    reason = unusable(base, new_text)
    if reason:
        raise GoadError(f'snapshot base {reason}')
    try:
        path = contained(base.lab_yml, new_text)
    except GoadError as e:
        raise GoadError(f'no snapshot qualifies and the base snapshot lab.yml is invalid ({e}): redeploy') from e
    raise GoadError(f'lab.yml dropped {path} since base: provision cannot remove it; redeploy')


def _provision(settings, runner, text: str, state: LabState) -> None:
    from goad.lab import provision as provisioning
    provisioning.provision(settings, runner, parse_lab(text, SOURCE), state, tags=ENABLE_TAGS)


def _state(settings) -> LabState:
    state = load_state(settings)
    if state is None:
        raise GoadError('no lab deployed: run goad lab deploy <lab>')
    return state


def enable(settings, runner, name: str, target: Optional[str]) -> str:
    state = _state(settings)
    path = working_lab_path(settings)
    new_text, target = add_entry(path.read_text(), name, target)
    path.write_text(new_text)
    try:
        _provision(settings, runner, new_text, state)
    except GoadError as e:
        raise GoadError(f'{e}: scenario {name}@{target} stays in lab.yml: run goad lab provision, '
                        f'or goad scenario disable {name} --target {target}') from e
    return target


def disable(settings, runner, name: str, target: Optional[str], yes: bool,
            ask: Callable[[str, bool], bool]) -> str:
    from goad.lab import snapshots
    from goad.lab.context import open_lab
    state = _state(settings)
    path = working_lab_path(settings)
    new_text, target = remove_entry(path.read_text(), name, target)
    snap = pick_snapshot(state, new_text)
    if not ask(f'Reset the lab to snapshot {snap} and replay the remaining scenarios? '
               f'Changes made inside the VMs since {snap} are lost.', yes):
        raise GoadError('cancelled')
    record = state.snapshot(snap)
    lab = open_lab(settings, runner, lab_yml=record.lab_yml)
    snapshots.reset(lab, snap)
    path.write_text(new_text)
    if scenarios.expand(_load(new_text), SOURCE) != scenarios.expand(_load(record.lab_yml), SOURCE):
        try:
            _provision(settings, runner, new_text, lab.state)
        except GoadError as e:
            raise GoadError(f'{e}: lab reset to {snap}; scenario {name}@{target} removed from lab.yml: '
                            f'run goad lab provision') from e
    return snap


def listing(text: Optional[str]) -> List[Tuple[str, str, str, str, str]]:
    catalogue = scenarios.load_catalogue()
    raw = _load(text) if text is not None else None
    rows = []
    for name in sorted(catalogue):
        scenario = catalogue[name]
        if raw is None:
            valid = enabled = ''
        else:
            valid = ', '.join(scenarios.valid_targets(raw, scenario.kind))
            enabled = ', '.join(e['target'] for e in _entries(raw) if e['name'] == name)
        rows.append((name, scenario.kind, scenario.description, valid, enabled))
    return rows


def scenario_accounts(text: str) -> List[Tuple[str, str, str]]:
    """(NETBIOS\\user, password, scope) for each user a scenario fragment adds (absent from the lab before expansion)."""
    raw = _load(text)
    entries = _entries(raw)
    if not entries:
        return []
    catalogue = scenarios.load_catalogue()
    expanded = scenarios.expand(raw, SOURCE, catalogue)
    rows = []
    for entry in entries:
        name, target = entry['name'], entry['target']
        fragment = scenarios.substitute(catalogue[name].fragment, scenarios.placeholders(raw, target))
        for domain, content in (fragment.get('domains') or {}).items():
            info = expanded['domains'][domain]
            existing = ((raw.get('domains') or {}).get(domain) or {}).get('users') or {}
            for user in (content or {}).get('users') or {}:
                if user in existing:
                    continue
                password = (info['users'][user] or {}).get('password') or expanded['password']
                rows.append((f'{info["netbios"]}\\{user}', password, f'scenario {name}@{target}'))
    return rows
