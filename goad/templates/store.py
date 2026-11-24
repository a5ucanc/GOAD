import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from goad import GoadError
from goad.host.paths import to_wsl
from goad.settings import OS_NAMES, Settings
from goad.state import templates_in_use
from goad.vmware.vmrun import Vmrun

OS_FAMILY = {'win2022': 'windows', 'win2025': 'windows', 'win11': 'windows', 'ubuntu2404': 'linux', 'kali': 'linux'}
BUILD_DIR = '.build'
META = 'template.json'
_NAME = re.compile(r'^(' + '|'.join(OS_NAMES) + r')-v(\d+)$')


@dataclass(frozen=True)
class Template:
    name: str
    os: str
    version: int
    vmx: str
    built_at: str
    packer_sha: str

    def write(self, folder: Path) -> None:
        (folder / META).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def read(cls, folder: Path) -> 'Template':
        return cls(**json.loads((folder / META).read_text()))


class TemplateStore:
    """Versioned templates under <template_root>\\<os>-v<n>\; unfinished builds live in .build\\."""

    def __init__(self, settings: Settings, vmrun: Vmrun, root: Optional[Path] = None):
        self.settings = settings
        self.vmrun = vmrun
        self.root = to_wsl(settings.template_root) if root is None else root

    def windows_dir(self, name: str) -> str:
        return f'{self.settings.template_root}\\{name}'

    def windows_vmx(self, name: str) -> str:
        return f'{self.windows_dir(name)}\\{name}.vmx'

    def list(self) -> List[Template]:
        if not self.root.is_dir():
            return []
        found = [Template.read(p) for p in self.root.iterdir()
                 if p.is_dir() and _NAME.match(p.name) and (p / META).is_file()]
        return sorted(found, key=lambda t: (t.os, t.version))

    def latest(self, os_name: str) -> Optional[Template]:
        versions = [t for t in self.list() if t.os == os_name]
        return versions[-1] if versions else None

    def next_version(self, os_name: str) -> int:
        """1 + the highest version used so far, counting aborted builds left in .build\\."""
        seen = [0]
        for folder in (self.root, self.root / BUILD_DIR):
            if folder.is_dir():
                for p in folder.iterdir():
                    match = _NAME.match(p.name)
                    if match and match.group(1) == os_name:
                        seen.append(int(match.group(2)))
        return max(seen) + 1

    def delete(self, name: str, yes: bool) -> None:
        from goad.cli import confirm
        folder = self.root / name
        if not _NAME.match(name) or not (folder / META).is_file():
            raise GoadError(f'no template named {name}: see goad template list')
        if name in templates_in_use(self.settings):
            raise GoadError(f'template {name} is used by the deployed lab: destroy the lab first')
        if not confirm(f'Delete template {name}?', yes):
            raise GoadError('cancelled')
        self.vmrun.delete_vm(self.windows_vmx(name))
        if folder.exists():
            shutil.rmtree(folder)
