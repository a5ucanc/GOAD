"""Reader for the lab state file (~/.goad/lab.json). Plan 2 owns writing it."""
import json
from typing import Set

from goad.settings import Settings


def templates_in_use(settings: Settings) -> Set[str]:
    path = settings.state_dir / 'lab.json'
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text()).get('templates', []))
