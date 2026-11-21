import re
import sys
from pathlib import Path, PurePosixPath
from typing import Union

from goad import GoadError

_WSL = re.compile(r'^/mnt/([a-zA-Z])(?:/(.*))?$')
_WIN = re.compile(r'^([a-zA-Z]):[\\/]?(.*)$')


def to_windows(path: Union[str, Path]) -> str:
    """/mnt/c/x/y -> C:\\x\\y. Pure string mapping, no wslpath call."""
    text = str(PurePosixPath(str(path)))
    match = _WSL.match(text)
    if not match:
        raise GoadError(f'path not on a Windows drive: {path}')
    drive, rest = match.group(1).upper(), match.group(2) or ''
    return f'{drive}:\\' + rest.replace('/', '\\')


def to_wsl(path: str) -> Path:
    """C:\\x\\y (or C:/x/y) -> /mnt/c/x/y."""
    match = _WIN.match(path)
    if not match:
        raise GoadError(f'path not on a Windows drive: {path}')
    drive, rest = match.group(1).lower(), match.group(2).replace('\\', '/').strip('/')
    return Path(f'/mnt/{drive}') / rest if rest else Path(f'/mnt/{drive}')


def ansible_bin(name: str) -> str:
    """The venv is not on PATH when ~/.goad/v2/bin/goad runs: prefer the binary next to the interpreter."""
    path = Path(sys.executable).parent / name
    return str(path) if path.exists() else name
