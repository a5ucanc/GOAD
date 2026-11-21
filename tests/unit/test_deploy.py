from types import SimpleNamespace

import pytest

from goad import GoadError
from goad.host.checks import Check
from goad.host.runner import FakeRunner, Result
from goad.lab import deploy as deploy_module
from goad.lab.deploy import Probes, deploy
from goad.lab.definition import shipped_lab
from goad.lab.remote import SETUP_USER
from goad.state import STEPS, SnapshotRecord, load_state, save_state, working_lab_path
from goad.templates.store import Template
from goad.vmware.vmx import Vmx


class CloneRunner(FakeRunner):
    """A successful clone writes a minimal .vmx at the destination."""

    def __init__(self, local):
        super().__init__()
        self.local = local

    def run(self, argv, timeout=None):
        result = super().run(argv, timeout)
        if result.ok and len(argv) > 3 and argv[3] == 'clone':
            path = self.local(argv[5])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('displayName = "clone"\n')
        return result


class FakeStore:
    def __init__(self):
        self.templates = {os_name: Template(f'{os_name}-v{v}', os_name, v, '', '', '')
                          for os_name, v in (('win2022', 1), ('win2025', 2))}

    def latest(self, os_name):
        return self.templates.get(os_name)

    def windows_vmx(self, name):
        return f'C:\\goad\\templates\\{name}\\{name}.vmx'


def fail_on(host):
    def marker(vmrun, vmx):
        return 'failed: x' if host in vmx else 'done'
    return marker


@pytest.fixture
def env(settings, tmp_path, monkeypatch):
    def local(path):
        return tmp_path / 'win' / path[3:].replace('\\', '/')

    monkeypatch.setattr(deploy_module, 'to_wsl', lambda p: local(p))
    removed_setup = []
    in_guest = set()   # IPs whose first boot finished in an earlier run: the short probe answers

    def wait_port(ip, port, timeout):
        if timeout == deploy_module.PROBE_TIMEOUT and ip not in in_guest:
            raise GoadError(f'{ip}:{port} not reachable after {timeout}s')

    probes = Probes(is_up=lambda ip: False, run_checks=lambda *a, **k: [Check('vmrun', True, '')],
                    firstboot_marker=lambda vmrun, vmx: 'done', sleep=lambda s: None, wait_port=wait_port,
                    check_psrp=lambda *a: None, check_ssh=lambda *a: None,
                    remove_setup_account=lambda ip, password: removed_setup.append(ip),
                    provision=lambda *a: False)
    return SimpleNamespace(settings=settings, fake=CloneRunner(local), store=FakeStore(), probes=probes,
                           local=local, removed_setup=removed_setup, in_guest=in_guest)


def test_setup_user():
    assert SETUP_USER == 'goad-setup'


def test_fresh_deploy_runs_first_three_steps(env):
    state = deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert state.step == 'finish'
    assert state.templates == ['win2022-v1', 'win2025-v2']
    assert state.hosts['srv02'].template == 'win2022-v1'
    clones = [a for a in env.fake.calls if a[3] == 'clone']
    assert len(clones) == 3 and '-cloneName=2domains-dc01' in [c[-1] for c in clones]
    vmx = Vmx.load(env.local(r'C:\goad\lab\srv02\srv02.vmx'))
    assert vmx['guestinfo.goad.ip'] == '192.168.56.22' and vmx['guestinfo.goad.dns'] == '192.168.56.11'
    assert vmx['memsize'] == '4096' and vmx['ethernet1.vnet'] == 'VMnet2'
    assert working_lab_path(env.settings).read_text() == shipped_lab('2domains').read_text()


def test_resume_skips_existing_clones(env):
    env.fake.respond(lambda a: a[3] == 'clone' and 'srv02' in a[5], Result(1, 'Error: disk full', ''))
    with pytest.raises(GoadError, match='srv02'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert load_state(env.settings).step == 'check'
    env.fake.calls.clear()
    env.fake._responses.clear()
    deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert [a[-1] for a in env.fake.calls if a[3] == 'clone'] == ['-cloneName=2domains-srv02']


def test_refuses_second_lab(env):
    deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    with pytest.raises(GoadError, match='already deployed'):
        deploy('1domain', env.settings, env.fake, env.store, probes=env.probes)


def test_refuses_busy_ip(env):
    env.probes.is_up = lambda ip: ip.endswith('.22')
    with pytest.raises(GoadError, match=r'192.168.56.22 \(srv02\)'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)


def test_refuses_missing_template(env):
    env.store.templates.pop('win2022')
    with pytest.raises(GoadError, match='goad template build win2022'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)


def test_refuses_failed_host_check(env):
    env.probes.run_checks = lambda *a, **k: [Check('vmrun', False, 'missing')]
    with pytest.raises(GoadError, match='vmrun: missing'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)


def test_refuses_leftover_vm_folder(env):
    env.local(r'C:\goad\lab\dc01').mkdir(parents=True)
    with pytest.raises(GoadError, match='leftover VM folder'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert load_state(env.settings) is None


def test_range_override_recorded(env):
    env.probes.firstboot_marker = fail_on('dc01')  # keep the lab undeployed so a re-run resumes
    with pytest.raises(GoadError, match='dc01'):
        deploy('1domain', env.settings, env.fake, env.store, ip_range='10.9.8', probes=env.probes)
    state = load_state(env.settings)
    assert state.ip_range == '10.9.8' and state.hosts['dc01'].ip == '10.9.8.10'
    with pytest.raises(GoadError, match='--range'):
        deploy('1domain', env.settings, env.fake, env.store, ip_range='10.9.7', probes=env.probes)


def test_full_deploy(env):
    state = deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert state.step == 'finish' and state.current == 'base'
    assert all(h.ready for h in state.hosts.values())
    assert set(state.durations) == set(STEPS)
    assert sorted(env.removed_setup) == ['192.168.56.10', '192.168.56.11', '192.168.56.22']
    snaps = [a for a in env.fake.calls if a[3] == 'snapshot']
    assert len(snaps) == 3 and all(a[5] == 'base' for a in snaps)
    assert state.snapshot('base').lab_yml == working_lab_path(env.settings).read_text()


def test_firstboot_failure_keeps_ready_hosts(env):
    env.probes.firstboot_marker = fail_on('srv02')
    with pytest.raises(GoadError, match='srv02'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    state = load_state(env.settings)
    assert state.step == 'configure'
    assert {h for h, s in state.hosts.items() if s.ready} == {'dc01', 'dc02'}


def test_resume_firstboot_only_waits_for_unready(env):
    env.probes.firstboot_marker = fail_on('srv02')
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    waited = []
    env.probes.firstboot_marker = lambda vmrun, vmx: waited.append(vmx) or 'done'
    assert deploy('2domains', env.settings, env.fake, env.store, probes=env.probes).step == 'finish'
    assert waited == [r'C:\goad\lab\srv02\srv02.vmx']


def test_provision_skipped_message(env, capsys):
    deploy('1domain', env.settings, env.fake, env.store, probes=env.probes)
    assert 'provisioning skipped' in capsys.readouterr().out


def snapshotted(env):
    return [a[4] for a in env.fake.calls if a[3] == 'snapshot']


def test_snapshot_failure_leaves_base_unrecorded(env):
    env.fake.respond(lambda a: a[3] == 'snapshot' and 'srv02' in a[4], Result(1, 'Error: disk full', ''))
    with pytest.raises(GoadError, match='snapshot failed on .*srv02'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    state = load_state(env.settings)
    assert state.step == 'provision' and state.snapshot('base') is None and state.current != 'base'


def test_resume_finish_skips_vms_with_base(env):
    env.fake.respond(lambda a: a[3] == 'snapshot' and 'srv02' in a[4], Result(1, 'Error: disk full', ''))
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    env.fake.calls.clear()
    env.fake._responses.clear()
    env.fake.respond(lambda a: a[3] == 'listSnapshots' and 'srv02' not in a[4], Result(0, 'Total snapshots: 1\nbase\n', ''))
    state = deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert snapshotted(env) == [r'C:\goad\lab\srv02\srv02.vmx']
    assert state.step == 'finish' and state.current == 'base'


def test_finish_replaces_stale_base_record(env):
    env.fake.respond(lambda a: a[3] == 'snapshot' and 'srv02' in a[4], Result(1, 'Error: disk full', ''))
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    state = load_state(env.settings)
    state.snapshots = [SnapshotRecord('base', '2000-01-01T00:00:00Z', 'stale', 'old'),
                       SnapshotRecord('base', '2000-01-02T00:00:00Z', 'dup', 'old')]
    save_state(env.settings, state)
    env.fake._responses.clear()
    state = deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    bases = [r for r in state.snapshots if r.name == 'base']
    assert len(bases) == 1 and bases[0].label == 'taken by deploy'
    assert bases[0].lab_yml == working_lab_path(env.settings).read_text()


def test_resume_skips_firstboot_wait_for_host_ready_in_guest(env):
    env.probes.firstboot_marker = fail_on('srv02')
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    state = load_state(env.settings)
    for host in state.hosts.values():
        host.ready = False   # flags lost, e.g. Ctrl-C during the first-boot wait
    save_state(env.settings, state)
    env.in_guest.update({'192.168.56.10', '192.168.56.11'})
    env.removed_setup.clear()
    waited = []

    def marker(vmrun, vmx):   # the marker is gone after a power cycle for hosts finished earlier
        if 'srv02' in vmx:
            waited.append(vmx)
            return 'done'
        return ''
    env.probes.firstboot_marker = marker
    assert deploy('2domains', env.settings, env.fake, env.store, probes=env.probes).step == 'finish'
    assert waited == [r'C:\goad\lab\srv02\srv02.vmx']
    assert sorted(env.removed_setup) == ['192.168.56.10', '192.168.56.11', '192.168.56.22']


def test_firstboot_starts_ready_hosts_too(env):
    env.probes.firstboot_marker = fail_on('srv02')
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    env.fake.calls.clear()   # the fake lists no running VM: the lab is powered off
    started = []
    env.probes.firstboot_marker = lambda vmrun, vmx: started.append(
        sorted(c[4] for c in env.fake.calls if c[3] == 'start')) or 'done'
    deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert started == [sorted(load_state(env.settings).hosts[h].vmx for h in ('dc01', 'dc02', 'srv02'))]


def test_resume_at_provision_starts_powered_off_vms(env):
    def fail(*a):
        raise GoadError('ansible-playbook failed (exit 2)')
    env.probes.provision = fail
    with pytest.raises(GoadError, match='ansible'):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert load_state(env.settings).step == 'firstboot'
    env.fake.calls.clear()   # the fake lists no running VM: the lab is powered off
    started_before = []
    env.probes.provision = lambda *a: started_before.append(
        len([c for c in env.fake.calls if c[3] == 'start'])) or False
    deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert started_before == [3]


def _boot_lab(env):
    """Deploy 1domain up to a failing first boot, then mark the host unready for a resume."""
    env.probes.firstboot_marker = fail_on('dc01')
    with pytest.raises(GoadError):
        deploy('1domain', env.settings, env.fake, env.store, probes=env.probes)


def test_resume_after_power_cycle_polls_until_host_answers(env):
    _boot_lab(env)
    env.in_guest.clear()
    polls = {'marker': 0, 'port': 0}
    sleeps = []

    def marker(vmrun, vmx):
        polls['marker'] += 1
        return ''

    def wait_port(ip, port, timeout):
        if timeout == deploy_module.PROBE_TIMEOUT:
            polls['port'] += 1
            if polls['port'] < 3:
                raise GoadError('not up yet')

    env.probes.firstboot_marker = marker
    env.probes.wait_port = wait_port
    env.probes.sleep = sleeps.append
    env.removed_setup.clear()
    assert deploy('1domain', env.settings, env.fake, env.store, probes=env.probes).step == 'finish'
    assert polls['marker'] == 3 and len(sleeps) == 2
    assert env.removed_setup and all(h.ready for h in load_state(env.settings).hosts.values())


def test_firstboot_failed_marker_raises_at_once(env):
    sleeps = []
    env.probes.firstboot_marker = lambda vmrun, vmx: 'failed: boom'
    env.probes.sleep = sleeps.append
    with pytest.raises(GoadError, match='first boot failed: boom'):
        deploy('1domain', env.settings, env.fake, env.store, probes=env.probes)
    assert sleeps == []


def test_firstboot_times_out_when_never_done(env, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(deploy_module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(deploy_module, 'FIRSTBOOT_TIMEOUT', 30)
    env.probes.firstboot_marker = lambda vmrun, vmx: ''

    def sleep(seconds):
        clock[0] += seconds
    env.probes.sleep = sleep
    with pytest.raises(GoadError, match='first boot did not finish in 30s'):
        deploy('1domain', env.settings, env.fake, env.store, probes=env.probes)
    assert clock[0] == 30


def test_step_check_requires_ansible(env):
    seen = {}

    def run_checks(*a, **k):
        seen.update(k)
        return [Check('vmrun', False, 'stop here')]

    env.probes.run_checks = run_checks
    with pytest.raises(GoadError):
        deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert seen['need_ansible'] is True
