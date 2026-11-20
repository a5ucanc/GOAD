import glob
import os
import re
import shutil
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

from goad import GoadError
from goad.host.paths import to_wsl

_WINDOWS_PATH = re.compile(r'^[a-zA-Z]:[\\/]')

OS_NAMES = ('win2022', 'win2025', 'win11', 'ubuntu2404')


@dataclass(frozen=True)
class IsoSource:
    # local Windows path or URL
    url: str
    # 'sha256:<hex>', 'file:<url of a checksum file>', or 'none' (Microsoft publishes no hash for eval ISOs)
    checksum: str


# Microsoft evaluation ISOs (go.microsoft.com links resolve to the current eval build).
DEFAULT_ISOS: Dict[str, IsoSource] = {
    'win2022': IsoSource('https://go.microsoft.com/fwlink/p/?LinkID=2195280&clcid=0x409&culture=en-us&country=US', 'none'),
    'win2025': IsoSource('https://go.microsoft.com/fwlink/?linkid=2293312&clcid=0x409&culture=en-us&country=us', 'none'),
    'win11': IsoSource('https://go.microsoft.com/fwlink/?linkid=2289031&clcid=0x409&culture=en-us&country=us', 'none'),
    'ubuntu2404': IsoSource('https://releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso',
                            'sha256:e907d92eeec9df64163a7e454cbc8d7755e8ddc7ed42f99dbc80c40f1a138433'),
}


@dataclass
class Settings:
    template_root: str = r'C:\goad\templates'
    lab_root: str = r'C:\goad\lab'
    vmware_dir: str = r'C:\Program Files (x86)\VMware\VMware Workstation'
    packer: str = 'packer.exe'
    vmnet: str = 'VMnet2'
    ip_range: str = '192.168.56'
    ca_certs_dir: Optional[str] = None
    isos: Dict[str, IsoSource] = field(default_factory=lambda: dict(DEFAULT_ISOS))
    state_dir: Path = field(default_factory=lambda: Path.home() / '.goad')


def default_config_path() -> Path:
    return Path.home() / '.goad' / 'config.yml'


def load_settings(path: Optional[Path] = None) -> Settings:
    path = default_config_path() if path is None else path
    settings = Settings()
    if not path.is_file():
        return settings
    data = yaml.safe_load(path.read_text()) or {}
    known = {f.name for f in fields(Settings)}
    for key, value in data.items():
        if key not in known:
            raise GoadError(f'unknown key in {path}: {key}')
        if key == 'isos':
            for os_name, iso in (value or {}).items():
                if os_name not in OS_NAMES:
                    raise GoadError(f'unknown OS in {path} isos: {os_name}')
                settings.isos[os_name] = IsoSource(url=str(iso['url']), checksum=str(iso.get('checksum', 'none')))
        elif key == 'state_dir':
            settings.state_dir = Path(value).expanduser()
        else:
            setattr(settings, key, None if value is None else str(value))
    return settings


def _winget_packer() -> List[str]:
    return sorted(glob.glob('/mnt/c/Users/*/AppData/Local/Microsoft/WinGet/Packages/Hashicorp.Packer_*/packer.exe'))


def resolve_packer(configured: str,
                   path_lookup: Callable[[str], Optional[str]] = shutil.which,
                   winget_glob: Callable[[], List[str]] = _winget_packer) -> Optional[str]:
    """WSL path of packer.exe: the configured path if it exists, else PATH, else the winget package folder."""
    if _WINDOWS_PATH.match(configured):
        configured = str(to_wsl(configured))
    if os.path.isfile(configured):
        return configured
    found = path_lookup(configured)
    if found:
        return found
    candidates = winget_glob()
    return candidates[0] if candidates else None
