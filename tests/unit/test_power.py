import pytest

from goad import GoadError
from goad.host.runner import Result
from goad.lab.power import SHUTDOWN_TIMEOUT, port_for, start_all, stop_all, wait_ready

VMS = {'dc01': r'C:\goad\lab\dc01\dc01.vmx', 'srv02': r'C:\goad\lab\srv02\srv02.vmx'}


def running(fake, *vmx):
    fake.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: {len(vmx)}\n' + '\n'.join(vmx), ''))


def test_start_all_skips_running(fake, vmrun):
    running(fake, VMS['dc01'])
    start_all(vmrun, VMS)
    starts = [a for a in fake.calls if a[3] == 'start']
    assert starts == [[vmrun.binary, '-T', 'ws', 'start', VMS['srv02'], 'nogui']]


def test_stop_all_falls_back_to_hard(fake, vmrun):
    running(fake, *VMS.values())
    fake.respond(lambda a: a[3] == 'stop' and a[5] == 'soft' and a[4] == VMS['dc01'], Result(1, 'Error: timed out', ''))
    stop_all(vmrun, VMS)
    stops = sorted((a[4], a[5]) for a in fake.calls if a[3] == 'stop')
    assert stops == [(VMS['dc01'], 'hard'), (VMS['dc01'], 'soft'), (VMS['srv02'], 'soft')]


def test_stop_all_hard_skips_soft(fake, vmrun):
    running(fake, *VMS.values())
    stop_all(vmrun, VMS, hard=True)
    assert sorted(a[5] for a in fake.calls if a[3] == 'stop') == ['hard', 'hard']


def test_stop_all_ignores_powered_off(fake, vmrun):
    running(fake)
    stop_all(vmrun, VMS)
    assert not [a for a in fake.calls if a[3] == 'stop']


def test_wait_ready_names_every_failure():
    def wait(ip, port, timeout): raise GoadError(f'{ip}:{port} not reachable')
    with pytest.raises(GoadError, match='dc01.*srv02'):
        wait_ready({'dc01': ('192.168.56.10', 5985), 'srv02': ('192.168.56.22', 5985)}, wait=wait)


def test_port_for():
    assert (port_for('windows'), port_for('linux')) == (5985, 22)


def test_spawn_recorded(fake):
    fake.spawn(['vmware.exe', 'x.vmx'])
    assert fake.calls == [['vmware.exe', 'x.vmx']]


def spy_timeouts(fake):
    seen = []
    original = fake.run

    def run(argv, timeout=None):
        seen.append((argv[3], argv[5] if argv[3] == 'stop' else None, timeout))
        return original(argv, timeout=timeout)
    fake.run = run
    return seen


def test_stop_all_soft_timeout_then_hard(fake, vmrun):
    running(fake, VMS['dc01'])
    fake.respond(lambda a: a[3] == 'stop' and a[5] == 'soft', Result(124, '', 'timed out after 180s: vmrun.exe'))
    seen = spy_timeouts(fake)
    stop_all(vmrun, {'dc01': VMS['dc01']})
    stops = [s for s in seen if s[0] == 'stop']
    assert stops == [('stop', 'soft', SHUTDOWN_TIMEOUT), ('stop', 'hard', 600)]
    assert SHUTDOWN_TIMEOUT == 180


def test_stop_all_one_failure_still_stops_the_rest(fake, vmrun):
    running(fake, *VMS.values())
    fake.respond(lambda a: a[3] == 'stop' and a[4] == VMS['dc01'], Result(1, 'Error: stuck', ''))
    with pytest.raises(GoadError, match='dc01'):
        stop_all(vmrun, VMS)
    assert (VMS['srv02'], 'soft') in [(a[4], a[5]) for a in fake.calls if a[3] == 'stop']


def test_start_all_starts_one_vm_at_a_time_in_order(fake, vmrun, monkeypatch):
    # parallel vmrun.exe starts race on the vmware-authd pipe (ERROR_PIPE_BUSY)
    active, overlap = [], []
    real_start = vmrun.start

    def start(vmx):
        active.append(vmx)
        overlap.append(len(active))
        try:
            real_start(vmx)
        finally:
            active.remove(vmx)

    monkeypatch.setattr(vmrun, 'start', start)
    monkeypatch.setattr('goad.lab.power.run_parallel', None)   # must not be used for starts
    running(fake)
    start_all(vmrun, VMS)
    starts = [a[4] for a in fake.calls if a[3] == 'start']
    assert starts == [VMS['dc01'], VMS['srv02']]
    assert overlap == [1, 1]


def test_start_all_keeps_going_after_a_failed_start(fake, vmrun):
    running(fake)
    fake.respond(lambda a: a[3] == 'start' and a[4] == VMS['dc01'], Result(1, 'Error: Unknown error', ''))
    with pytest.raises(GoadError, match=r'start failed on dc01: .*Unknown error'):
        start_all(vmrun, VMS)
    assert [a[4] for a in fake.calls if a[3] == 'start'] == [VMS['dc01'], VMS['srv02']]
