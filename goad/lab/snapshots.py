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


def take(lab: Lab, label: Optional[str] = None, now=datetime.now) -> SnapshotRecord:
    taken = now(timezone.utc)
    name = label if label is not None else f'snap-{taken.strftime("%Y%m%d-%H%M%S")}'
    if not _NAME.match(name):
        raise GoadError(f'bad snapshot name {name!r}: use letters, digits, . _ - (max 64)')
    if name == PROTECTED or lab.state.snapshot(name):
        raise GoadError(f'snapshot {name} already exists')
    start = time.monotonic()
    stop_all(lab.vmrun, lab.vms())
    run_parallel(lab.vms(), lambda host, vmx: lab.vmrun.snapshot(vmx, name), 'snapshot').raise_if_failed('snapshot')
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


def reset(lab: Lab, name: str = PROTECTED, wait=wait_ready) -> float:
    record = lab.state.snapshot(name)
    if record is None:
        raise GoadError(f'unknown snapshot {name}')
    found = _listed(lab)
    missing = [host for host in lab.vms() if name not in found[host]]
    if missing:
        raise GoadError(f'snapshot {name} is missing on {", ".join(missing)}: nothing was changed')
    start = time.monotonic()
    stop_all(lab.vmrun, lab.vms(), hard=True)
    run_parallel(lab.vms(), lambda host, vmx: lab.vmrun.revert(vmx, name), 'revert').raise_if_failed('revert')
    path = working_lab_path(lab.settings)
    path.write_text(record.lab_yml)
    lab.definition = parse_lab(record.lab_yml, str(path))
    lab.state.current = name
    lab.save()
    start_all(lab.vmrun, lab.vms())
    wait(lab.endpoints())
    elapsed = time.monotonic() - start
    console.print(f'lab reset to {name} in {elapsed:.0f}s')
    return elapsed
