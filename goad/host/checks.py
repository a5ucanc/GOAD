import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from goad.host.paths import to_wsl
from goad.host.runner import Runner
from goad.settings import Settings, resolve_packer

MIN_PACKER = (1, 11)
MIN_FREE_GB = 100


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


def run_checks(runner: Runner, settings: Settings, need_packer: bool,
               exists: Callable[[str], bool] = os.path.isfile,
               disk_usage=shutil.disk_usage,
               packer_path: Callable[[str], Optional[str]] = resolve_packer,
               cert_files: Callable[[str], List[Path]] = _cert_files) -> List[Check]:
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
