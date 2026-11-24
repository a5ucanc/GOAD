"""goad template import kali: turn Kali's prebuilt VMware image into a template.

Kali publishes a ready VMware VM (a .7z archive) instead of an installer goad would drive with Packer. goad
downloads it with curl.exe (resumable, like the Windows ISOs in iso.py), checks it against Kali's SHA256SUMS,
extracts it with 7-Zip, and runs kali-prep.sh inside it through VMware Tools so that clones configure
themselves from guestinfo through cloud-init, exactly like ubuntu2404 clones.
"""
import datetime
import shutil
import time
from pathlib import Path
from typing import Callable, List

from rich.console import Console

from goad import GoadError
from goad.host.checks import SEVENZIP_MISSING, _cert_files, find_7zip, run_checks
from goad.host.runner import Runner
from goad.settings import Settings
from goad.templates.iso import _sha256
from goad.templates.store import BUILD_DIR, Template, TemplateStore
from goad.vmware.vmrun import VmrunError, norm_vmx
from goad.vmware.vmx import Vmx

KALI_URL = 'https://cdimage.kali.org/kali-2026.3/kali-linux-2026.3-vmware-amd64.7z'
KALI_SUMS = 'https://cdimage.kali.org/kali-2026.3/SHA256SUMS'
PREP_SCRIPT = Path(__file__).with_name('kali-prep.sh')
GUEST_SCRIPT = '/tmp/kali-prep.sh'
# the image's default account
KALI_USER = KALI_PASSWORD = 'kali'
CACHE = 'kali'   # <template_root>\.build\kali\: archive, SHA256SUMS, extraction; not a template name

DOWNLOAD_TIMEOUT = 6 * 3600    # ~3 GB
EXTRACT_TIMEOUT = 3600
TOOLS_TIMEOUT = 900            # power-on until VMware Tools answers
PREP_TIMEOUT = 3600            # apt-get update + install inside the guest
POWEROFF_TIMEOUT = 900         # kali-prep.sh powers the guest off shortly after it exits
POLL_INTERVAL = 10
# VMware can hold the VM folder open for a moment after the guest powers off
RENAME_ATTEMPTS = 6
RENAME_DELAY = 5

console = Console()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _expected_sha(sums: Path, filename: str) -> str:
    for line in sums.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip('*') == filename:
            return parts[0].lower()
    raise GoadError(f'{filename} is not listed in {sums}')


def _download(runner: Runner, url: str, windows_dest: str, timeout: float) -> None:
    result = runner.run(['curl.exe', '-L', '--fail', '--retry', '5', '--retry-all-errors', '-C', '-',
                         '-o', windows_dest, url], timeout=timeout)
    if not result.ok:
        raise GoadError(f'download of {url} failed ({result.stderr.strip() or result.code}); '
                        f'run goad template import kali again to resume')


def _ensure_archive(runner: Runner, url: str, sums_url: str, cache: Path, windows_cache: str) -> str:
    """Windows path of the verified archive. A cached archive is reused only when its SHA256 matches."""
    filename = url.rsplit('/', 1)[-1]
    archive, part = cache / filename, cache / f'{filename}.part'
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'SHA256SUMS').unlink(missing_ok=True)
    _download(runner, sums_url, f'{windows_cache}\\SHA256SUMS', timeout=300)
    expected = _expected_sha(cache / 'SHA256SUMS', filename)

    if archive.is_file():
        console.print(f'checking cached {filename}')
        if _sha256(archive) == expected:
            return f'{windows_cache}\\{filename}'
        archive.unlink()

    console.print(f'downloading {url} to {windows_cache}')
    _download(runner, url, f'{windows_cache}\\{filename}.part', timeout=DOWNLOAD_TIMEOUT)
    part.rename(archive)
    console.print(f'hashing {filename}')
    actual = _sha256(archive)
    if actual != expected:
        archive.unlink()
        raise GoadError(f'{filename} checksum mismatch: expected {expected}, got {actual}; '
                        f'the download was deleted, run goad template import kali again')
    return f'{windows_cache}\\{filename}'


def _extract(runner: Runner, archive: str, cache: Path, windows_cache: str) -> Path:
    """Folder holding the extracted .vmx."""
    sevenzip = find_7zip()
    if sevenzip is None:
        raise GoadError(SEVENZIP_MISSING)
    target = cache / 'extract'
    if target.exists():
        shutil.rmtree(target)
    console.print(f'extracting {archive}')
    result = runner.run([sevenzip, 'x', '-y', f'-o{windows_cache}\\extract', archive], timeout=EXTRACT_TIMEOUT)
    if not result.ok:
        raise GoadError(f'7-Zip could not extract {archive}: {result.stderr.strip() or result.stdout.strip()[-500:]}')
    found = sorted(target.rglob('*.vmx'))
    if len(found) != 1:
        raise GoadError(f'expected one .vmx in {windows_cache}\\extract, found {len(found)}')
    return found[0].parent


def _move_built(built: Path, final: Path, windows_built: str) -> None:
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            built.rename(final)
            return
        except OSError as e:
            if attempt == RENAME_ATTEMPTS:
                raise GoadError(f'could not move {windows_built} into place ({e}): the prepared VM stays there; '
                                f'delete it and run goad template import kali again') from e
            time.sleep(RENAME_DELAY)


def _wait(condition: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise GoadError(f'{what} after {timeout:.0f}s')
        time.sleep(POLL_INTERVAL)


def _tools_running(store: TemplateStore, vmx: str) -> bool:
    try:
        return store.vmrun.tools_state(vmx) == 'running'
    except VmrunError:
        return False


def import_kali(settings: Settings, runner: Runner, store: TemplateStore, url: str = KALI_URL,
                sums_url: str = KALI_SUMS, checks: Callable = run_checks,
                cert_files: Callable[[str], List[Path]] = _cert_files) -> Template:
    failed = [c for c in checks(runner, settings, need_packer=False, need_7zip=True) if not c.ok]
    if failed:
        raise GoadError('host checks failed: ' + '; '.join(f'{c.name}: {c.detail}' for c in failed))

    version = store.next_version('kali')
    name = f'kali-v{version}'
    cache = store.root / BUILD_DIR / CACHE
    windows_cache = f'{settings.template_root}\\{BUILD_DIR}\\{CACHE}'
    archive = _ensure_archive(runner, url, sums_url, cache, windows_cache)
    extracted = _extract(runner, archive, cache, windows_cache)

    # prepared in .build\ like a Packer build: an aborted import never looks like a finished template
    built = store.root / BUILD_DIR / name
    extracted.rename(built)
    shutil.rmtree(cache / 'extract', ignore_errors=True)
    (extracted_vmx,) = built.glob('*.vmx')
    local_vmx = built / f'{name}.vmx'
    extracted_vmx.rename(local_vmx)
    vmx_file = Vmx.load(local_vmx)
    vmx_file['displayName'] = name
    vmx_file['uuid.action'] = 'create'    # no "moved or copied?" question on a headless power-on
    vmx_file['msg.autoAnswer'] = 'TRUE'
    vmx_file.save()
    # copied beside the archive: vmrun.exe needs a Windows path, and the script needs LF line endings
    (cache / 'kali-prep.sh').write_bytes(PREP_SCRIPT.read_bytes().replace(b'\r\n', b'\n'))

    vmx = f'{settings.template_root}\\{BUILD_DIR}\\{name}\\{name}.vmx'
    vmrun = store.vmrun
    try:
        vmrun.start(vmx)
        console.print(f'{name} started, waiting for VMware Tools')
        _wait(lambda: _tools_running(store, vmx), TOOLS_TIMEOUT, f'VMware Tools not running in {name}')
        vmrun.copy_to_guest(vmx, KALI_USER, KALI_PASSWORD, f'{windows_cache}\\kali-prep.sh', GUEST_SCRIPT)
        # ca_certs_dir: trusted by every template; kali-prep.sh imports /tmp/goad-ca-*
        certs = cert_files(settings.ca_certs_dir) if settings.ca_certs_dir else []
        for index, cert in enumerate(certs):
            vmrun.copy_to_guest(vmx, KALI_USER, KALI_PASSWORD, f'{settings.ca_certs_dir}\\{cert.name}',
                                f'/tmp/goad-ca-{index}{cert.suffix.lower()}')
        console.print(f'running kali-prep.sh in {name} (log in the guest: /var/log/goad-kali-prep.log)')
        vmrun.run_in_guest(vmx, KALI_USER, KALI_PASSWORD, '/bin/bash', [GUEST_SCRIPT, KALI_PASSWORD],
                           timeout=PREP_TIMEOUT)
        _wait(lambda: norm_vmx(vmx) not in vmrun.running(), POWEROFF_TIMEOUT, f'{name} did not power off')
    except GoadError as e:
        try:
            vmrun.stop(vmx, hard=True)
        except VmrunError:
            pass   # already off
        raise GoadError(f'{e} (the unfinished VM is kept in {settings.template_root}\\{BUILD_DIR}\\{name})') from e

    final = store.root / name
    _move_built(built, final, f'{settings.template_root}\\{BUILD_DIR}\\{name}')
    store.vmrun.snapshot(store.windows_vmx(name), 'base')
    template = Template(name=name, os='kali', version=version, vmx=store.windows_vmx(name),
                        built_at=_now(), packer_sha='')
    # template.json last: its presence marks a finished template
    template.write(final)
    return template
