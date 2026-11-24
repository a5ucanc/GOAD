"""Helpers shared by the live tests: PSRP into lab hosts and lab health checks."""
import os
import subprocess
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


def wait_logon(ip: str, user: str, timeout: float = 600, password: str = PASSWORD) -> float:
    """Wait until user logs in to ip over PSRP; return seconds. Deploy, start and reset return when
    WinRM listens, which on a DC comes before AD DS accepts domain logons (NTLM answers 401)."""
    start = time.monotonic()
    while True:
        try:
            psrp(ip, user, 'hostname', password=password)
            return time.monotonic() - start
        except Exception as e:  # any PSRP or WinRM failure means "not yet"
            if time.monotonic() - start >= timeout:
                raise AssertionError(f'{ip} as {user}: no logon after {timeout:.0f} s: {type(e).__name__}: {e}')
        time.sleep(POLL)


def _health_problem(settings, runner) -> str:
    """'' when the 2domains lab is healthy, otherwise the first check that failed."""
    lab = open_lab(settings, runner, need_definition=False)
    off = [row.host for row in lifecycle.status(lab) if row.power != 'running']
    if off:
        return f'powered off: {", ".join(off)}'
    ip = {name: host.ip for name, host in lab.state.hosts.items()}
    # The domain logon comes before the secure-channel query: a logon makes Netlogon set up a channel
    # that failed at boot (the member started before its DC); the query alone never retries it.
    checks = [('dc01', 'Administrator', '(Get-ADDomain).DNSRoot', 'sevenkingdoms.local'),
              ('dc02', 'Administrator', '(Get-ADDomain).DNSRoot', 'north.sevenkingdoms.local'),
              ('srv02', 'NORTH\\Administrator', 'whoami', 'north\\administrator'),
              ('srv02', 'Administrator', 'Test-ComputerSecureChannel', 'True')]
    for host, user, script, expected in checks:
        try:
            got = psrp(ip[host], user, script)
        except Exception as e:  # any PSRP or WinRM failure means "not yet"
            return f'{host} as {user}: {script}: {type(e).__name__}: {e}'
        if got != expected:
            return f'{host}: {script} returned {got!r}, expected {expected!r}'
    return ''


def wait_healthy(settings, runner, timeout: float = 300) -> float:
    """Wait until every VM runs, AD answers on dc01 and dc02, and srv02 logs in a domain user and has its
    secure channel; return seconds."""
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


def ssh(ip: str, command: str, user: str = 'goad', password: str = PASSWORD, timeout: float = 120) -> str:
    """Run command on a Linux lab host over SSH (password login through sshpass); return stdout."""
    done = subprocess.run(['sshpass', '-e', 'ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                           '-o', 'LogLevel=ERROR', '-o', 'ConnectTimeout=15', f'{user}@{ip}', command],
                          env={**os.environ, 'SSHPASS': password}, capture_output=True, text=True,
                          timeout=timeout)
    assert done.returncode == 0, f'{ip}: {command}: exit {done.returncode}: {done.stderr.strip()}'
    return done.stdout.strip()
