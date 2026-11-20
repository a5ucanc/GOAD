import pytest

from goad import GoadError
from goad.host.runner import Result
from goad.templates import smoke
from goad.templates.store import Template, TemplateStore


@pytest.fixture
def store(tmp_path, settings, vmrun):
    root = tmp_path / 'templates'
    root.mkdir()
    folder = root / 'win2025-v2'
    folder.mkdir()
    Template('win2025-v2', 'win2025', 2, r'C:\goad\templates\win2025-v2\win2025-v2.vmx', 't', 'x').write(folder)
    return TemplateStore(settings, vmrun, root=root)


@pytest.fixture
def lab_root(tmp_path, monkeypatch):
    root = tmp_path / 'lab'
    monkeypatch.setattr(smoke, 'local_dir', lambda windows_path: root / windows_path.split('\\')[-1])
    return root


@pytest.fixture
def quick(monkeypatch):
    calls = []
    monkeypatch.setattr(smoke, 'is_up', lambda ip: False)
    monkeypatch.setattr(smoke, 'wait_port', lambda ip, port, timeout=300: calls.append(('port', ip, port)))
    monkeypatch.setattr(smoke, 'check_psrp', lambda ip, user, password, hostname: calls.append(('psrp', ip, hostname)))
    monkeypatch.setattr(smoke, 'check_ssh', lambda ip: calls.append(('ssh', ip)))
    return calls


def _write_vmx_on_clone(fake, lab_root):
    def on_clone(argv):
        if 'clone' in argv:
            folder = lab_root / 'win2025'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'win2025.vmx').write_text('memsize = "2048"\n')
        return False
    fake.respond(on_clone, Result(0, '', ''))


def test_smoke_clones_from_latest_base(store, settings, fake, lab_root, quick):
    _write_vmx_on_clone(fake, lab_root)
    seen = {}

    def capture(argv):
        if argv[3] == 'start':
            seen['vmx'] = (lab_root / 'win2025' / 'win2025.vmx').read_text()
        return False
    fake.respond(capture, Result(0, '', ''))
    fake.respond(lambda a: 'readVariable' in a, Result(0, 'done\n', ''))
    smoke.smoke_test('win2025', settings, fake, store)
    clone = next(c for c in fake.calls if 'clone' in c)
    assert clone[3:] == ['clone', r'C:\goad\templates\win2025-v2\win2025-v2.vmx',
                         r'C:\goad\lab\.smoke\win2025\win2025.vmx', 'linked', '-snapshot=base', '-cloneName=smoke-win2025']
    vmx = seen['vmx']
    assert 'guestinfo.goad.ip = "192.168.56.250"' in vmx and 'ethernet1.vnet = "VMnet2"' in vmx
    assert ('psrp', '192.168.56.250', 'smoke-win2025') in quick
    assert [c[3] for c in fake.calls if c[3] in ('stop', 'deleteVM')] == ['stop', 'deleteVM']
    assert not (lab_root / 'win2025').exists()


def test_smoke_cleans_up_on_firstboot_timeout(store, settings, fake, lab_root, quick, monkeypatch):
    _write_vmx_on_clone(fake, lab_root)
    monkeypatch.setattr(smoke, 'FIRSTBOOT_TIMEOUT', 0)
    with pytest.raises(GoadError, match='first boot did not finish'):
        smoke.smoke_test('win2025', settings, fake, store)
    actions = [c[3] for c in fake.calls]
    assert 'stop' in actions and 'deleteVM' in actions
    assert not (lab_root / 'win2025').exists()


def test_no_template_built(store, settings, fake, lab_root, quick):
    with pytest.raises(GoadError, match='goad template build win11'):
        smoke.smoke_test('win11', settings, fake, store)


def test_refuses_when_test_ip_in_use(store, settings, fake, lab_root, quick, monkeypatch):
    monkeypatch.setattr(smoke, 'is_up', lambda ip: True)
    with pytest.raises(GoadError, match='192.168.56.250'):
        smoke.smoke_test('win2025', settings, fake, store)
    assert not [c for c in fake.calls if 'clone' in c]


def test_wait_firstboot_returns_when_done(vmrun, fake):
    fake.respond(lambda a: 'readVariable' in a, Result(0, 'done', ''))
    smoke.wait_firstboot(vmrun, 'x.vmx', timeout=5, interval=0)
