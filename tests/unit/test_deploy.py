from types import SimpleNamespace

import pytest

from goad import GoadError
from goad.host.checks import Check
from goad.host.runner import FakeRunner, Result
from goad.lab import deploy as deploy_module
from goad.lab.deploy import Probes, deploy
from goad.lab.definition import shipped_lab
from goad.lab.remote import SETUP_USER
from goad.state import load_state, working_lab_path
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


@pytest.fixture
def env(settings, tmp_path, monkeypatch):
    def local(path):
        return tmp_path / 'win' / path[3:].replace('\\', '/')

    monkeypatch.setattr(deploy_module, 'to_wsl', lambda p: local(p))
    probes = Probes(is_up=lambda ip: False, run_checks=lambda *a, **k: [Check('vmrun', True, '')])
    return SimpleNamespace(settings=settings, fake=CloneRunner(local), store=FakeStore(), probes=probes,
                           local=local)


def test_setup_user():
    assert SETUP_USER == 'goad-setup'


def test_fresh_deploy_runs_first_three_steps(env):
    state = deploy('2domains', env.settings, env.fake, env.store, probes=env.probes)
    assert state.step == 'configure'
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
    state = deploy('1domain', env.settings, env.fake, env.store, ip_range='10.9.8', probes=env.probes)
    assert state.ip_range == '10.9.8' and state.hosts['dc01'].ip == '10.9.8.10'
    with pytest.raises(GoadError, match='--range'):
        deploy('1domain', env.settings, env.fake, env.store, ip_range='10.9.7', probes=env.probes)
