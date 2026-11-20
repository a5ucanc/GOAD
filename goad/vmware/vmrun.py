from typing import List

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

    def _run(self, *args: str, timeout: float = 600) -> str:
        argv = [self.binary, '-T', 'ws', *args]
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

    def stop(self, vmx: str, hard: bool = False) -> None:
        self._run('stop', vmx, 'hard' if hard else 'soft')

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
