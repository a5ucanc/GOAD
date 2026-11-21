"""Whole-lab power: start, stop and readiness for every VM of a lab."""
import time
from typing import Dict, Tuple

from goad.templates.smoke import wait_port
from goad.vmware.parallel import ParallelResult, console, run_parallel
from goad.vmware.vmrun import Vmrun, VmrunError, norm_vmx

SHUTDOWN_TIMEOUT = 180
READY_TIMEOUT = 900


def port_for(family: str) -> int:
    return 5985 if family == 'windows' else 22


def _powered(vmrun: Vmrun, vms: Dict[str, str], want_running: bool) -> Dict[str, str]:
    up = set(vmrun.running())
    return {name: vmx for name, vmx in vms.items() if (norm_vmx(vmx) in up) == want_running}


def start_all(vmrun: Vmrun, vms: Dict[str, str]) -> None:
    """Start powered-off VMs one at a time, in lab order.

    Concurrent vmrun.exe starts race on the vmware-authd pipe (ERROR_PIPE_BUSY): some
    fail with "Unknown error" and some boot with the lab NIC disconnected. A failed
    start does not stop the others; all failures are raised together at the end.
    """
    result = ParallelResult()
    for name, vmx in _powered(vmrun, vms, want_running=False).items():
        started = time.monotonic()
        try:
            vmrun.start(vmx)
        except Exception as e:  # report every VM's outcome, whatever went wrong
            result.failed[name] = str(e) or type(e).__name__
            console.print(f'start {name} [red]failed[/red]: {result.failed[name]}')
        else:
            result.ok.append(name)
            console.print(f'start {name} [green]ok[/green] ({time.monotonic() - started:.0f}s)')
    result.raise_if_failed('start')


def stop_all(vmrun: Vmrun, vms: Dict[str, str], hard: bool = False) -> None:
    def stop(name: str, vmx: str) -> None:
        if hard:
            vmrun.stop(vmx, hard=True)
            return
        try:
            vmrun.stop(vmx, timeout=SHUTDOWN_TIMEOUT)
        except VmrunError:
            vmrun.stop(vmx, hard=True)

    todo = _powered(vmrun, vms, want_running=True)
    run_parallel(todo, stop, 'stop').raise_if_failed('stop')


def wait_ready(endpoints: Dict[str, Tuple[str, int]], timeout: float = READY_TIMEOUT, wait=wait_port) -> None:
    run_parallel(endpoints, lambda name, ep: wait(ep[0], ep[1], timeout), 'ready').raise_if_failed('readiness')
