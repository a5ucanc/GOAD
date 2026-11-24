"""goad extension add and remove: edit the extensions list of the working lab.yml on a deployed lab."""
from typing import Callable, Optional

from goad import GoadError
from goad.lab import extensions, scenarios
from goad.lab.definition import parse_lab
from goad.lab.scenario_ops import ENABLE_TAGS, SOURCE, _dump, _entries, _load, contained
from goad.state import LabState, SnapshotRecord, load_state, save_state, working_lab_path


def add_entry(text: str, name: str, lab_name: str) -> str:
    """text with extension name appended to its extensions list."""
    raw = _load(text)
    catalogue = extensions.load_catalogue()
    if name not in catalogue:
        raise GoadError(f'unknown extension {name}: see goad extension list')
    if lab_name not in catalogue[name].labs:
        raise GoadError(f'extension {name} does not apply to lab {lab_name}')
    names = extensions.entries(raw)
    if name in names:
        raise GoadError(f'extension {name} is already installed')
    raw['extensions'] = names + [name]
    new_text = _dump(raw)
    parse_lab(new_text, SOURCE)
    return new_text


def remove_entry(text: str, name: str) -> str:
    """text without extension name; only the most recently added one, and only when no scenario needs it."""
    raw = _load(text)
    names = extensions.entries(raw)
    if name not in names:
        raise GoadError(f'extension {name} is not installed')
    last = names[-1]
    if name != last:
        raise GoadError(f'extension {name} was added before {last}: remove {last} first')
    hosts = set(extensions.extension_hosts(raw, name))
    entries = _entries(raw)
    if entries:
        catalogue = scenarios.load_catalogue()
        dependents = [f'{e["name"]}@{e["target"]}' for e in entries
                      if getattr(catalogue.get(e['name']), 'requires', None) == name or e['target'] in hosts]
        if dependents:
            raise GoadError(f'scenarios depend on extension {name}: disable {", ".join(dependents)} first')
    names.remove(name)
    if names:
        raw['extensions'] = names
    else:
        raw.pop('extensions', None)
    new_text = _dump(raw)
    parse_lab(new_text, SOURCE)
    return new_text


def _deployed(settings) -> LabState:
    state = load_state(settings)
    if state is None:
        raise GoadError('no lab deployed: run goad lab deploy <lab>')
    if not state.deployed:
        raise GoadError(f'lab {state.lab} is not deployed: finish goad lab deploy {state.lab} first')
    return state


def add(settings, runner, store, name: str, probes=None) -> SnapshotRecord:
    from goad.lab import snapshots
    from goad.lab.context import open_lab
    from goad.lab.deploy import Probes, add_hosts, step_provision
    probes = probes or Probes()
    state = _deployed(settings)
    path = working_lab_path(settings)
    text = path.read_text()
    resume = state.pending_extension == name and name in extensions.entries(_load(text))
    if not resume:
        pending = state.pending_extension
        if pending and pending != name:
            raise GoadError(f'extension {pending} is half added: run goad extension add {pending} again to resume, '
                            f'or goad extension remove {pending}')
        text = add_entry(text, name, state.lab)
        path.write_text(text)
        state.pending_extension = name
        save_state(settings, state)
    lab = open_lab(settings, runner)
    label = f'ext-{name}'
    try:
        new = [h for h in lab.definition.hosts if h not in lab.state.hosts or not lab.state.hosts[h].ready]
        add_hosts(lab, store, probes, new)
        step_provision(lab, probes)
        record = lab.state.snapshot(label)
        if record is not None and snapshots.unusable(record, text) is not None:
            snapshots.delete(lab, label)
            record = None
        if record is None:
            record = snapshots.take(lab, label=label)
    except GoadError as e:
        lab.save()
        raise GoadError(f'{e}: run goad extension add {name} again to resume') from e
    lab.state.pending_extension = None
    lab.save()
    return record


def _pick(state: LabState, new_text: str, name: str) -> SnapshotRecord:
    from goad.lab.snapshots import unusable
    for record in reversed(state.snapshots):
        if unusable(record, new_text) is not None:
            continue
        try:
            if contained(record.lab_yml, new_text) is None:
                return record
        except GoadError:
            continue   # a record whose lab.yml no longer parses cannot be a reset target
    raise GoadError(f'no snapshot without extension {name}: redeploy')


def remove(settings, runner, name: str, yes: bool, ask: Callable[[str, bool], bool]) -> str:
    """Delete the VMs only name brings, reset to the newest snapshot without it, replay scenarios.
    Returns the snapshot reset to."""
    from goad.lab import snapshots
    from goad.lab.context import open_lab
    from goad.lab.lifecycle import delete_vms
    state = _deployed(settings)
    path = working_lab_path(settings)
    current = path.read_text()
    new_text = remove_entry(current, name)
    doomed = extensions.extension_hosts(_load(current), name)
    record = _pick(state, new_text, name)
    snap = record.name
    question = f'reset the lab to snapshot {snap}? Changes made inside the VMs since {snap} are lost.'
    question = f'Delete VMs {", ".join(doomed)} and {question}' if doomed else question[0].upper() + question[1:]
    if not ask(question, yes):
        raise GoadError('cancelled')
    lab = open_lab(settings, runner, lab_yml=record.lab_yml)
    if doomed:
        delete_vms(settings, lab.vmrun, {h: lab.state.hosts[h].vmx for h in doomed if h in lab.state.hosts},
                   folders=doomed)
        for host in doomed:
            lab.state.hosts.pop(host, None)
        lab.state.templates = sorted({h.template for h in lab.state.hosts.values()})
        lab.save()
    snapshots.reset(lab, snap, current_text=new_text)
    for held in [r.name for r in lab.state.snapshots if name in snapshots.recorded_extensions(r.lab_yml)]:
        snapshots.delete(lab, held)
    if lab.state.pending_extension == name:
        lab.state.pending_extension = None
        lab.save()
    path.write_text(new_text)
    if scenarios.expand(_load(new_text), SOURCE) != scenarios.expand(_load(record.lab_yml), SOURCE):
        from goad.lab import provision as provisioning
        try:
            provisioning.provision(settings, runner, parse_lab(new_text, SOURCE), lab.state, tags=ENABLE_TAGS)
        except GoadError as e:
            raise GoadError(f'{e}: lab reset to {snap}; extension {name} removed from lab.yml: '
                            f'run goad lab provision') from e
    return snap
