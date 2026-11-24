import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import yaml

from goad.host.paths import ansible_bin, to_wsl
from goad.host.runner import Runner
from goad.settings import Settings, resolve_packer

MIN_PACKER = (1, 11)
MIN_FREE_GB = 100
MIN_ANSIBLE = (2, 16)
REPO = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO / 'ansible' / 'requirements.yml'
SEVENZIP_DEFAULT = '/mnt/c/Program Files/7-Zip/7z.exe'
SEVENZIP_MISSING = '7-Zip not found: winget install 7zip.7zip'


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _adapter_ipv4(ipconfig: str, adapter: str) -> Optional[str]:
    """IPv4 address of `Ethernet adapter <adapter>:` in ipconfig output, or None."""
    current = None
    for raw in ipconfig.splitlines():
        line = raw.rstrip()
        header = re.match(r'^\S.*adapter (.+):$', line)
        if header:
            current = header.group(1)
            continue
        if current == adapter:
            match = re.match(r'^\s+IPv4 Address[ .]*: ([\d.]+)', line)
            if match:
                return match.group(1)
    return None


def _cert_files(folder: str) -> List[Path]:
    path = to_wsl(folder)
    if not path.is_dir():
        return []
    return [p for p in path.iterdir() if p.suffix.lower() in ('.cer', '.crt')]


def find_7zip(path_lookup: Callable[[str], Optional[str]] = shutil.which,
              exists: Callable[[str], bool] = os.path.isfile) -> Optional[str]:
    """WSL path of 7z.exe (extracts the Kali image): PATH first, else the default install folder."""
    found = path_lookup('7z.exe')
    if found:
        return found
    return SEVENZIP_DEFAULT if exists(SEVENZIP_DEFAULT) else None


def _ansible_checks(runner: Runner) -> List[Check]:
    result = runner.run([ansible_bin('ansible-playbook'), '--version'], timeout=60)
    match = re.search(r'core (\d+)\.(\d+)', result.stdout)
    if result.code == 127 or not match:
        return [Check('ansible', False, 'ansible-playbook not found: pip install -e . in the goad venv')]
    first = result.stdout.strip().splitlines()[0]
    if (int(match.group(1)), int(match.group(2))) < MIN_ANSIBLE:
        return [Check('ansible', False, f'need ansible-core >= 2.16, found: {first}')]
    checks = [Check('ansible', True, f'ansible-core {match.group(1)}.{match.group(2)}')]
    listing = runner.run([ansible_bin('ansible-galaxy'), 'collection', 'list', '--format', 'json'], timeout=120)
    try:
        installed = {name for path in json.loads(listing.stdout).values() for name in path}
    except (ValueError, AttributeError):
        installed = set()
    wanted = [c['name'] for c in yaml.safe_load(REQUIREMENTS.read_text())['collections']]
    missing = sorted(set(wanted) - installed)
    if missing:
        checks.append(Check('collections', False, f'missing Ansible collections {", ".join(missing)}: '
                                                  'ansible-galaxy collection install -r ansible/requirements.yml'))
    else:
        checks.append(Check('collections', True, ', '.join(wanted)))
    return checks


def run_checks(runner: Runner, settings: Settings, need_packer: bool, need_ansible: bool = False,
               exists: Callable[[str], bool] = os.path.isfile,
               disk_usage=shutil.disk_usage,
               packer_path: Callable[[str], Optional[str]] = resolve_packer,
               cert_files: Callable[[str], List[Path]] = _cert_files,
               need_7zip: bool = False,
               sevenzip_path: Callable[[], Optional[str]] = find_7zip) -> List[Check]:
    """need_7zip: only goad template import asks for it (the Kali image is a .7z archive)."""
    checks: List[Check] = []

    vmrun = to_wsl(settings.vmware_dir) / 'vmrun.exe'
    checks.append(Check('vmrun', exists(str(vmrun)),
                        str(vmrun) if exists(str(vmrun)) else f'vmrun.exe not found in {settings.vmware_dir}'))

    if need_packer:
        packer = packer_path(settings.packer)
        if packer is None:
            checks.append(Check('packer', False, 'packer.exe not found: install Packer 1.11+ or set packer in ~/.goad/config.yml'))
        else:
            out = runner.run([packer, 'version'], timeout=60).stdout
            match = re.search(r'v(\d+)\.(\d+)\.(\d+)', out)
            version = tuple(int(x) for x in match.groups()) if match else None
            ok = version is not None and version[:2] >= MIN_PACKER
            checks.append(Check('packer', ok, out.strip() if ok else f'need Packer >= 1.11, found: {out.strip() or "nothing"}'))

    if need_ansible:
        checks.extend(_ansible_checks(runner))

    if need_7zip:
        sevenzip = sevenzip_path()
        checks.append(Check('7zip', sevenzip is not None, sevenzip or SEVENZIP_MISSING))

    adapter = f'VMware Network Adapter {settings.vmnet}'
    want = f'{settings.ip_range}.1'
    found = _adapter_ipv4(runner.run(['ipconfig.exe'], timeout=60).stdout, adapter)
    hint = f'create {settings.vmnet} as host-only {settings.ip_range}.0/24 in Virtual Network Editor (needs admin)'
    if found == want:
        checks.append(Check('vmnet', True, f'{settings.vmnet} {want}'))
    elif found is None:
        checks.append(Check('vmnet', False, f'{settings.vmnet} not found: {hint}'))
    else:
        checks.append(Check('vmnet', False, f'{settings.vmnet} has {found}, expected {want}: {hint}'))

    drive = to_wsl(settings.template_root[:3])
    free_gb = disk_usage(str(drive)).free / 1024 ** 3
    checks.append(Check('disk', free_gb >= MIN_FREE_GB,
                        f'{free_gb:.0f} GB free on {settings.template_root[:2]} (need {MIN_FREE_GB} GB)'))

    if settings.ca_certs_dir:
        certs = cert_files(settings.ca_certs_dir)
        checks.append(Check('ca_certs', bool(certs),
                            f'{len(certs)} certificate(s) in {settings.ca_certs_dir}' if certs
                            else f'no .cer/.crt files in {settings.ca_certs_dir}'))
    return checks
