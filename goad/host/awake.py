"""Keep the Windows host from sleeping while a long job (a template build) runs.

A host that sleeps cuts every VM off the network, and Packer then fails and deletes the build VM.
A helper powershell.exe holds ES_SYSTEM_REQUIRED through SetThreadExecutionState for as long as it lives.
"""
import contextlib
import subprocess
from typing import Iterator, List

from rich.console import Console

console = Console()

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED; the request ends when the process exits
_SCRIPT = (
    "$s = Add-Type -PassThru -Name Awake -Namespace Goad -MemberDefinition "
    "'[DllImport(\"kernel32.dll\")] public static extern uint SetThreadExecutionState(uint f);'; "
    "[void]$s::SetThreadExecutionState([uint32]'0x80000001'); "
    "while ($true) { Start-Sleep -Seconds 3600 }"
)


def _spawn(argv: List[str]):
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextlib.contextmanager
def keep_host_awake() -> Iterator[None]:
    try:
        process = _spawn(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _SCRIPT])
    except OSError as e:
        console.print(f'[yellow]warning:[/yellow] cannot keep the host awake ({e}): disable sleep during the build')
        process = None
    try:
        yield
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
