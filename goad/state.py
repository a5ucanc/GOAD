"""Lab state file (~/.goad/lab.json): deploy progress, hosts, snapshots."""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from goad import GoadError
from goad.settings import Settings

STEPS = ('check', 'clone', 'configure', 'firstboot', 'provision', 'finish')


@dataclass
class HostState:
    vmx: str   # Windows path
    template: str
    hostname: str
    ip: str
    ready: bool = False


@dataclass
class SnapshotRecord:
    name: str
    taken_at: str   # ISO 8601 UTC, seconds
    label: str
    lab_yml: str


@dataclass
class LabState:
    lab: str
    ip_range: str
    step: str = ''
    hosts: Dict[str, HostState] = field(default_factory=dict)
    templates: List[str] = field(default_factory=list)
    snapshots: List[SnapshotRecord] = field(default_factory=list)
    current: Optional[str] = None
    durations: Dict[str, float] = field(default_factory=dict)

    @property
    def deployed(self) -> bool:
        return self.step == 'finish'

    def snapshot(self, name: str) -> Optional[SnapshotRecord]:
        for snap in self.snapshots:
            if snap.name == name:
                return snap
        return None


def state_path(settings: Settings) -> Path:
    return settings.state_dir / 'lab.json'


def working_lab_path(settings: Settings) -> Path:
    return settings.state_dir / 'lab.yml'


def inventory_path(settings: Settings) -> Path:
    return settings.state_dir / 'inventory.yml'


def log_dir(settings: Settings) -> Path:
    return settings.state_dir / 'logs'


def load_state(settings: Settings) -> Optional[LabState]:
    path = state_path(settings)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        data['hosts'] = {k: HostState(**v) for k, v in data.get('hosts', {}).items()}
        data['snapshots'] = [SnapshotRecord(**s) for s in data.get('snapshots', [])]
        return LabState(**data)
    except (ValueError, TypeError, AttributeError) as e:   # JSONDecodeError is a ValueError
        raise GoadError(f'corrupt lab state {path}: {e}: fix the file or delete it')


def save_state(settings: Settings, state: LabState) -> None:
    path = state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(asdict(state), indent=2))
    os.replace(tmp, path)


def delete_state(settings: Settings) -> None:
    for path in (state_path(settings), working_lab_path(settings), inventory_path(settings)):
        path.unlink(missing_ok=True)


def templates_in_use(settings: Settings) -> Set[str]:
    path = state_path(settings)
    if not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text()).get('templates', []))
    except (ValueError, TypeError, AttributeError) as e:   # JSONDecodeError is a ValueError
        raise GoadError(f'corrupt lab state {path}: {e}: fix the file or delete it')
