"""ISO sources for template builds.

Microsoft publishes no hash for its evaluation ISOs, and Packer with checksum 'none' would cache and
reuse a download cut short. goad downloads those ISOs itself with curl.exe (resumable, fails on a short
transfer), hashes the finished file once, and hands Packer a local path plus its sha256.
"""
import hashlib
import re
from pathlib import Path
from typing import Tuple

from rich.console import Console

from goad import GoadError
from goad.host.paths import to_wsl
from goad.host.runner import Runner
from goad.settings import Settings

console = Console()
_WINDOWS_PATH = re.compile(r'^[a-zA-Z]:[\\/]')


def local_dir(windows_path: str) -> Path:
    return to_wsl(windows_path)


def iso_root(settings: Settings) -> str:
    return settings.template_root.rsplit('\\', 1)[0] + '\\iso'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(16 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def ensure_iso(os_name: str, settings: Settings, runner: Runner) -> Tuple[str, str]:
    """(iso_url, iso_checksum) to give Packer for os_name."""
    source = settings.isos[os_name]
    if _WINDOWS_PATH.match(source.url) or source.checksum != 'none':
        return source.url, source.checksum

    root = iso_root(settings)
    folder = local_dir(root)
    final, part, sha_file = folder / f'{os_name}.iso', folder / f'{os_name}.iso.part', folder / f'{os_name}.iso.sha256'
    windows_final = f'{root}\\{os_name}.iso'
    if final.is_file() and sha_file.is_file():
        return windows_final, 'sha256:' + sha_file.read_text().strip()

    folder.mkdir(parents=True, exist_ok=True)
    console.print(f'downloading {os_name} ISO to {windows_final}')
    result = runner.run(['curl.exe', '-L', '--fail', '--retry', '5', '--retry-all-errors', '-C', '-',
                         '-o', f'{root}\\{os_name}.iso.part', source.url], timeout=6 * 3600)
    if not result.ok:
        raise GoadError(f'download of {os_name} ISO failed ({result.stderr.strip() or result.code}); '
                        f'run the build again to resume')
    part.rename(final)
    console.print(f'hashing {final.name}')
    checksum = _sha256(final)
    sha_file.write_text(checksum + '\n')
    return windows_final, 'sha256:' + checksum
