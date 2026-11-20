import pytest

from goad import GoadError
from goad.host.checks import Check
from goad.host.runner import Result
from goad.templates.build import build_template
from goad.templates.store import TemplateStore

PACKER = '/w/packer.exe'


@pytest.fixture
def store(tmp_path, settings, vmrun):
    root = tmp_path / 'templates'
    root.mkdir()
    return TemplateStore(settings, vmrun, root=root)


def _build(store, settings, fake, checks_ok=True, os_name='win2025'):
    return build_template(os_name, settings, fake, store,
                          checks=lambda *a, **k: [Check('packer', checks_ok, 'x')],
                          packer_path=lambda s: PACKER)


def _packer_build_writes_vmx(store, fake, name='win2025-v1', code=0):
    def on_build(argv):
        if argv[0] == PACKER and argv[1] == 'build':
            out = store.root / '.build' / name
            out.mkdir(parents=True, exist_ok=True)
            (out / f'{name}.vmx').write_text('')
            return True
        return False
    fake.respond(on_build, Result(code, '', ''))


def test_build_argv(store, settings, fake):
    _packer_build_writes_vmx(store, fake)
    _build(store, settings, fake)
    packer_calls = [c for c in fake.calls if c[0] == PACKER]
    assert packer_calls[0][1] == 'init' and packer_calls[1][1] == 'build'
    build = packer_calls[1]
    assert '-force' in build
    assert '-var' in build and 'vm_name=win2025-v1' in build
    assert r'output_directory=C:\goad\templates\.build\win2025-v1' in build
    assert any(a.startswith('-var-file=') and a.endswith(r'packer\windows\win2025.pkrvars.hcl') for a in build)
    assert build[-1].endswith(r'packer\windows')
    assert 'password=Aa1234567890!' in build
    assert 'iso_checksum=none' in build


def test_success_takes_base_snapshot_and_moves(store, settings, fake):
    _packer_build_writes_vmx(store, fake)
    template = _build(store, settings, fake)
    assert template.name == 'win2025-v1' and template.os == 'win2025' and template.version == 1
    assert (store.root / 'win2025-v1' / 'template.json').is_file()
    assert not (store.root / '.build' / 'win2025-v1').exists()
    snap = [c for c in fake.calls if 'snapshot' in c]
    assert snap[-1][3:] == ['snapshot', r'C:\goad\templates\win2025-v1\win2025-v1.vmx', 'base']
    assert [t.name for t in store.list()] == ['win2025-v1']


def test_failure_keeps_build_dir_and_names_log(store, settings, fake):
    _packer_build_writes_vmx(store, fake, code=1)
    with pytest.raises(GoadError, match=r'template-win2025-v1\.log'):
        _build(store, settings, fake)
    assert (store.root / '.build' / 'win2025-v1').is_dir()
    assert store.list() == []
    assert not [c for c in fake.calls if 'snapshot' in c]


def test_failed_checks_stop_before_packer(store, settings, fake):
    with pytest.raises(GoadError, match='packer'):
        _build(store, settings, fake, checks_ok=False)
    assert not [c for c in fake.calls if c[0] == PACKER]


def test_unknown_os_rejected(store, settings, fake):
    with pytest.raises(GoadError, match='win7'):
        _build(store, settings, fake, os_name='win7')


def test_linux_uses_ubuntu_dir(store, settings, fake):
    _packer_build_writes_vmx(store, fake, name='ubuntu2404-v1')
    _build(store, settings, fake, os_name='ubuntu2404')
    build = [c for c in fake.calls if c[0] == PACKER][1]
    assert build[-1].endswith(r'packer\ubuntu')
    assert any(a.endswith(r'packer\ubuntu\ubuntu2404.pkrvars.hcl') for a in build)
