"""Helpers shared by the live tests: PSRP into lab hosts and lab health checks."""
import time

from goad.lab import lifecycle
from goad.lab.context import open_lab

PASSWORD = 'Aa1234567890!'
POLL = 10


def psrp(ip: str, user: str, script: str, password: str = PASSWORD) -> str:
    from pypsrp.client import Client
    output, streams, had_errors = Client(ip, username=user, password=password, ssl=False, auth='ntlm',
                                         cert_validation=False).execute_ps(script)
    assert not had_errors, f'{ip}: {script}: {[str(e) for e in streams.error]}'
    return output.strip()


def _health_problem(settings, runner) -> str:
    """'' when the 2domains lab is healthy, otherwise the first check that failed."""
    lab = open_lab(settings, runner, need_definition=False)
    off = [row.host for row in lifecycle.status(lab) if row.power != 'running']
    if off:
        return f'powered off: {", ".join(off)}'
    ip = {name: host.ip for name, host in lab.state.hosts.items()}
    checks = [('dc01', '(Get-ADDomain).DNSRoot', 'sevenkingdoms.local'),
              ('dc02', '(Get-ADDomain).DNSRoot', 'north.sevenkingdoms.local'),
              ('srv02', 'Test-ComputerSecureChannel', 'True')]
    for host, script, expected in checks:
        try:
            got = psrp(ip[host], 'Administrator', script)
        except Exception as e:  # any PSRP or WinRM failure means "not yet"
            return f'{host}: {script}: {type(e).__name__}: {e}'
        if got != expected:
            return f'{host}: {script} returned {got!r}, expected {expected!r}'
    return ''


def wait_healthy(settings, runner, timeout: float = 300) -> float:
    """Wait until every VM runs, AD answers on dc01 and dc02 and srv02 has its secure channel; return seconds."""
    start = time.monotonic()
    while True:
        problem = _health_problem(settings, runner)
        if not problem:
            return time.monotonic() - start
        if time.monotonic() - start >= timeout:
            raise AssertionError(f'lab not healthy after {timeout:.0f} s: {problem}')
        time.sleep(POLL)


def add_marker(dc_ip: str, name: str) -> None:
    psrp(dc_ip, 'Administrator', f"New-ADUser -Name '{name}' -SamAccountName '{name}'")


def marker_exists(dc_ip: str, name: str) -> bool:
    return bool(psrp(dc_ip, 'Administrator', f"Get-ADUser -Filter \"SamAccountName -eq '{name}'\""))
