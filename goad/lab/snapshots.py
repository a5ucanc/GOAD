"""Whole-lab snapshots: every VM, powered off, with a copy of the working lab.yml in the record."""
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from rich.console import Console

from goad import GoadError
from goad.lab.context import Lab
from goad.lab.definition import parse_lab
from goad.lab.power import start_all, stop_all, wait_ready
from goad.lab.provision import check_compatible
from goad.state import SnapshotRecord, working_lab_path
from goad.vmware.parallel import run_parallel

console = Console()

PROTECTED = 'base'
_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


@dataclass
class SnapshotRow:
    record: SnapshotRecord
    missing_on: List[str]


def _listed(lab: Lab) -> Dict[str, List[str]]:
    """Snapshot names per host, one listSnapshots per VM."""
    found: Dict[str, List[str]] = {}

    def list_one(name: str, vmx: str) -> None:
        found[name] = lab.vmrun.snapshots(vmx)

    run_parallel(lab.vms(), list_one, 'list snapshots').raise_if_failed('list snapshots')
    return found


def _undo_partial(lab: Lab, name: str, done: List[str]) -> None:
    """Best effort after a failed take: drop the new snapshot where it exists, power the lab back on."""
    def drop(host: str, vmx: str) -> None:
        lab.vmrun.delete_snapshot(vmx, name)

    run_parallel({host: lab.vms()[host] for host in done}, drop, 'undo snapshot')
    try:
        start_all(lab.vmrun, lab.vms())
    except GoadError as error:
        console.print(f'could not power the lab back on: {error}')


def take(lab: Lab, label: Optional[str] = None, now=datetime.now) -> SnapshotRecord:
    taken = now(timezone.utc)
    name = label if label is not None else f'snap-{taken.strftime("%Y%m%d-%H%M%S")}'
    if not _NAME.match(name):
        raise GoadError(f'bad snapshot name {name!r}: use letters, digits, . _ - (max 64)')
    if name == PROTECTED or lab.state.snapshot(name):
        raise GoadError(f'snapshot {name} already exists')
    check_compatible(lab.definition, lab.state)   # never record a lab.yml that reset could not restore
    start = time.monotonic()
    stop_all(lab.vmrun, lab.vms())
    result = run_parallel(lab.vms(), lambda host, vmx: lab.vmrun.snapshot(vmx, name), 'snapshot')
    if result.failed:
        _undo_partial(lab, name, result.ok)
        result.raise_if_failed('snapshot')
    record = SnapshotRecord(name=name, taken_at=taken.strftime('%Y-%m-%dT%H:%M:%SZ'),
                            label=label or '', lab_yml=working_lab_path(lab.settings).read_text())
    lab.state.snapshots.append(record)
    lab.state.current = name
    lab.save()
    start_all(lab.vmrun, lab.vms())
    console.print(f'snapshot {name} taken in {time.monotonic() - start:.0f}s')
    return record


def list_snapshots(lab: Lab) -> List[SnapshotRow]:
    found = _listed(lab)
    return [SnapshotRow(record, [host for host in lab.vms() if record.name not in found[host]])
            for record in lab.state.snapshots]


def delete(lab: Lab, name: str) -> None:
    if name == PROTECTED:
        raise GoadError('the base snapshot is protected')
    if lab.state.snapshot(name) is None:
        raise GoadError(f'unknown snapshot {name}')
    found = _listed(lab)
    todo = {host: vmx for host, vmx in lab.vms().items() if name in found[host]}
    run_parallel(todo, lambda host, vmx: lab.vmrun.delete_snapshot(vmx, name), 'delete snapshot') \
        .raise_if_failed('delete snapshot')
    lab.state.snapshots = [s for s in lab.state.snapshots if s.name != name]
    if lab.state.current == name:
        lab.state.current = None
    lab.save()


def recorded_extensions(lab_yml: str) -> List[str]:
    """The raw extensions: list of a lab.yml text; empty when absent or unreadable."""
    import yaml

    from goad.lab.extensions import entries
    try:
        raw = yaml.safe_load(lab_yml)
    except yaml.YAMLError:
        return []
    return entries(raw) if isinstance(raw, dict) else []


def unusable(record: SnapshotRecord, current_text: str) -> Optional[str]:
    """Why a snapshot cannot be a reset target, or None when its extension list matches the current one."""
    held, current = recorded_extensions(record.lab_yml), recorded_extensions(current_text)
    if held == current:
        return None
    newer = [x for x in current if x not in held]
    if newer:
        return f'predates extension {newer[-1]}: run goad extension remove {newer[-1]} first'
    extra = [x for x in held if x not in current]
    if extra:
        return f'holds extension {extra[-1]}, which is not installed'
    return f'has extensions in a different order than lab.yml: {", ".join(held)}'


def reset(lab: Lab, name: str = PROTECTED, wait=wait_ready, current_text: Optional[str] = None) -> float:
    record = lab.state.snapshot(name)
    if record is None:
        raise GoadError(f'unknown snapshot {name}')
    path = working_lab_path(lab.settings)
    reason = unusable(record, path.read_text() if current_text is None else current_text)
    if reason:
        raise GoadError(f'snapshot {name} {reason}')
    definition = parse_lab(record.lab_yml, f'snapshot {name} lab.yml')
    check_compatible(definition, lab.state)   # before any VM is listed or powered off
    found = _listed(lab)
    missing = [host for host in lab.vms() if name not in found[host]]
    if missing:
        raise GoadError(f'snapshot {name} is missing on {", ".join(missing)}: nothing was changed')
    start = time.monotonic()
    stop_all(lab.vmrun, lab.vms(), hard=True)
    result = run_parallel(lab.vms(), lambda host, vmx: lab.vmrun.revert(vmx, name), 'revert')
    if result.failed:
        raise GoadError(f'revert to {name} failed on {", ".join(sorted(result.failed))}: the lab is half reverted '
                        f'and powered off; run goad lab reset {name} again')
    path.write_text(record.lab_yml)
    lab.definition = definition
    lab.state.current = name
    lab.save()
    start_all(lab.vmrun, lab.vms())
    wait(lab.endpoints())
    elapsed = time.monotonic() - start
    console.print(f'lab reset to {name} in {elapsed:.0f}s')
    return elapsed
