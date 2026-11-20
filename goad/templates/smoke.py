"""goad template test: prove a template deployable (linked clone, first boot, readiness), then delete the clone.

wait_firstboot, wait_port, check_psrp and check_ssh are reused by lab deploy.
"""
import shutil
import socket
import subprocess
import time
from pathlib import Path

from rich.console import Console

from goad import GoadError
from goad.host.paths import to_wsl
from goad.host.runner import Runner
from goad.settings import Settings
from goad.templates.build import PASSWORD
from goad.templates.store import OS_FAMILY, TemplateStore
from goad.vmware.guestinfo import FIRSTBOOT_DONE, FIRSTBOOT_KEY, GuestConfig, configure_hardware, lab_mac, write_guestinfo
from goad.vmware.vmrun import Vmrun, VmrunError
from goad.vmware.vmx import Vmx

console = Console()
FIRSTBOOT_TIMEOUT = 1200
SMOKE_OCTET = 250


def local_dir(windows_path: str) -> Path:
    return to_wsl(windows_path)


def is_up(ip: str) -> bool:
    return subprocess.run(['ping', '-c', '1', '-W', '1', ip], capture_output=True).returncode == 0


def wait_firstboot(vmrun: Vmrun, vmx: str, timeout: float = FIRSTBOOT_TIMEOUT, interval: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if vmrun.read_guest_var(vmx, FIRSTBOOT_KEY) == FIRSTBOOT_DONE:
                return
        except VmrunError:
            pass  # VMware Tools not running yet
        if time.monotonic() >= deadline:
            raise GoadError(f'first boot did not finish in {timeout:.0f}s')
        time.sleep(interval)


def wait_port(ip: str, port: int, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((ip, port), timeout=5):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise GoadError(f'{ip}:{port} not reachable after {timeout:.0f}s')
            time.sleep(5)


def check_psrp(ip: str, user: str, password: str, hostname: str) -> None:
    from pypsrp.client import Client
    output, _, had_errors = Client(ip, username=user, password=password, ssl=False, auth='ntlm',
                                   cert_validation=False).execute_ps('hostname')
    if had_errors or output.strip().lower() != hostname.lower():
        raise GoadError(f'PSRP on {ip}: expected hostname {hostname}, got {output.strip()!r}')


def check_ssh(ip: str) -> None:
    with socket.create_connection((ip, 22), timeout=10) as sock:
        banner = sock.recv(64).decode(errors='replace')
    if not banner.startswith('SSH-2.0'):
        raise GoadError(f'SSH on {ip}: unexpected banner {banner!r}')


def smoke_test(os_name: str, settings: Settings, runner: Runner, store: TemplateStore) -> float:
    template = store.latest(os_name)
    if template is None:
        raise GoadError(f'no {os_name} template: run goad template build {os_name}')
    ip = f'{settings.ip_range}.{SMOKE_OCTET}'
    if is_up(ip):
        raise GoadError(f'{ip} already answers: the template test needs that address free')

    vmrun = store.vmrun
    hostname = f'smoke-{os_name}'
    folder = f'{settings.lab_root}\\.smoke\\{os_name}'
    vmx_path = f'{folder}\\{os_name}.vmx'
    family = OS_FAMILY[os_name]
    start = time.monotonic()

    def phase(text: str) -> None:
        console.print(f'{text} ({time.monotonic() - start:.0f}s)')

    try:
        vmrun.clone_linked(template.vmx, vmx_path, 'base', hostname)
        phase(f'cloned {template.name}')
        vmx = Vmx.load(local_dir(folder) / f'{os_name}.vmx')
        mac = lab_mac(ip)
        configure_hardware(vmx, cpus=2, mem_mb=4096, vmnet=settings.vmnet, lab_mac=mac)
        write_guestinfo(vmx, GuestConfig(hostname=hostname, ip=ip, prefix=24, gateway=None, dns=[ip],
                                         admin_password=PASSWORD, lab_mac=mac), family)
        vmx.save()
        vmrun.start(vmx_path)
        phase('started')
        wait_firstboot(vmrun, vmx_path, timeout=FIRSTBOOT_TIMEOUT)
        phase('first boot done')
        if family == 'windows':
            wait_port(ip, 5985)
            check_psrp(ip, 'Administrator', PASSWORD, hostname)
            phase('PSRP ok')
        else:
            wait_port(ip, 22)
            check_ssh(ip)
            phase('SSH ok')
        seconds = time.monotonic() - start
        console.print(f'template {template.name} ok in {seconds:.0f}s')
        return seconds
    finally:
        for action in (lambda: vmrun.stop(vmx_path, hard=True), lambda: vmrun.delete_vm(vmx_path)):
            try:
                action()
            except VmrunError:
                pass  # already off, or never created
        leftover = local_dir(folder)
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
