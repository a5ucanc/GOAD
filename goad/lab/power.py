"""Whole-lab power: start, stop and readiness for every VM of a lab."""
from typing import Dict, Tuple

from goad.templates.smoke import wait_port
from goad.vmware.parallel import run_parallel
from goad.vmware.vmrun import Vmrun, VmrunError, norm_vmx

SHUTDOWN_TIMEOUT = 180
READY_TIMEOUT = 900


def port_for(family: str) -> int:
    return 5985 if family == 'windows' else 22


def _powered(vmrun: Vmrun, vms: Dict[str, str], want_running: bool) -> Dict[str, str]:
    up = set(vmrun.running())
    return {name: vmx for name, vmx in vms.items() if (norm_vmx(vmx) in up) == want_running}


def start_all(vmrun: Vmrun, vms: Dict[str, str]) -> None:
    todo = _powered(vmrun, vms, want_running=False)
    run_parallel(todo, lambda name, vmx: vmrun.start(vmx), 'start').raise_if_failed('start')


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
