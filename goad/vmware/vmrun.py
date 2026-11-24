from typing import List, Tuple

from goad import GoadError
from goad.host.paths import to_wsl
from goad.host.runner import Runner
from goad.settings import Settings


class VmrunError(GoadError):
    pass


def norm_vmx(path: str) -> str:
    return path.strip().replace('\\', '/').lower()


class Vmrun:
    """vmrun.exe -T ws. Every method takes Windows .vmx paths."""

    def __init__(self, runner: Runner, settings: Settings):
        self.runner = runner
        self.binary = str(to_wsl(settings.vmware_dir) / 'vmrun.exe')

    def _run(self, *args: str, timeout: float = 600, guest: Tuple[str, str] = ()) -> str:
        """guest: (user, password) for guest operations, which need VMware Tools running in the guest."""
        auth = ['-gu', guest[0], '-gp', guest[1]] if guest else []
        argv = [self.binary, '-T', 'ws', *auth, *args]
        result = self.runner.run(argv, timeout=timeout)
        # vmrun reports some failures with exit code 0 and "Error: ..." on stdout
        if not result.ok or result.stdout.lstrip().startswith('Error:'):
            detail = (result.stdout.strip() or result.stderr.strip() or f'exit code {result.code}')
            raise VmrunError(f'vmrun {args[0]} failed: {detail}')
        return result.stdout

    @staticmethod
    def _lines(output: str) -> List[str]:
        return [line.strip() for line in output.splitlines()[1:] if line.strip()]

    def clone_linked(self, src_vmx: str, dest_vmx: str, snapshot: str, name: str) -> None:
        self._run('clone', src_vmx, dest_vmx, 'linked', f'-snapshot={snapshot}', f'-cloneName={name}')

    def start(self, vmx: str) -> None:
        self._run('start', vmx, 'nogui')

    def stop(self, vmx: str, hard: bool = False, timeout: float = 600) -> None:
        self._run('stop', vmx, 'hard' if hard else 'soft', timeout=timeout)

    def running(self) -> List[str]:
        return [norm_vmx(line) for line in self._lines(self._run('list', timeout=60))]

    def snapshot(self, vmx: str, name: str) -> None:
        self._run('snapshot', vmx, name)

    def revert(self, vmx: str, name: str) -> None:
        self._run('revertToSnapshot', vmx, name)

    def delete_snapshot(self, vmx: str, name: str) -> None:
        self._run('deleteSnapshot', vmx, name)

    def snapshots(self, vmx: str) -> List[str]:
        return self._lines(self._run('listSnapshots', vmx, timeout=60))

    def read_guest_var(self, vmx: str, key: str) -> str:
        return self._run('readVariable', vmx, 'guestVar', key, timeout=60).strip()

    def delete_vm(self, vmx: str) -> None:
        self._run('deleteVM', vmx)

    def tools_state(self, vmx: str) -> str:
        """'running' once VMware Tools answers in the guest; else 'installed', 'unknown' or ''."""
        return self._run('checkToolsState', vmx, timeout=60).strip()

    def copy_to_guest(self, vmx: str, user: str, password: str, src: str, dest: str) -> None:
        """src: Windows path on the host."""
        self._run('copyFileFromHostToGuest', vmx, src, dest, timeout=300, guest=(user, password))

    def run_in_guest(self, vmx: str, user: str, password: str, program: str, args: List[str],
                     timeout: float = 600) -> None:
        """Run program in the guest and wait for it; a non-zero exit code raises VmrunError."""
        self._run('runProgramInGuest', vmx, program, *args, timeout=timeout, guest=(user, password))
