import pytest

from goad import GoadError
from goad.cli import NeedsConfirmation
from goad.host.runner import Result
from goad.lab import lifecycle as lifecycle_module
from goad.lab.lifecycle import creds, destroy, status, vm_console, vm_start, vm_stop
from goad.state import HostState, LabState, load_state, save_state


@pytest.fixture(autouse=True)
def local_paths(monkeypatch, tmp_path):
    """Map C:\\ paths under tmp_path so no test touches the real /mnt/c."""
    def local(path):
        text = str(path)
        if len(text) > 2 and text[1] == ':':
            return tmp_path / 'wsl' / text[3:].replace('\\', '/')
        return tmp_path / 'wsl' / text.lstrip('/')
    monkeypatch.setattr(lifecycle_module, 'to_wsl', local)
    return local


def test_status_power(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: 1\n{lab.vms()["dc01"]}\n', ''))
    rows = {r.host: r for r in status(lab)}
    assert rows['dc01'].power == 'running' and rows['srv02'].power == 'off'
    assert rows['srv02'].ip == '192.168.56.22'


def test_destroy_half_deployed(settings, fake, monkeypatch, tmp_path):
    save_state(settings, LabState(lab='2domains', ip_range='192.168.56', step='check',
                                  hosts={'dc01': HostState(r'C:\goad\lab\dc01\dc01.vmx', 'win2025-v1', 'kingslanding', '192.168.56.10')}))
    fake.respond(lambda a: a[3] == 'deleteVM', Result(1, 'Error: The file does not exist', ''))
    destroy(settings, fake, yes=True)
    assert load_state(settings) is None


def test_destroy_removes_folders(settings, fake, deployed, local_paths):
    folder = local_paths(r'C:\goad\lab\dc01')
    folder.mkdir(parents=True)
    (folder / 'dc01.vmx').write_text('x')
    destroy(settings, fake, yes=True)
    assert not folder.exists()
    assert load_state(settings) is None


def test_destroy_no_lab(settings, fake):
    with pytest.raises(GoadError, match='no lab deployed'):
        destroy(settings, fake, yes=True)


def test_destroy_non_tty_needs_yes(settings, fake, deployed, monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(NeedsConfirmation):
        destroy(settings, fake, yes=False)
    assert load_state(settings) is not None


def test_creds(lab):
    rows = creds(lab)
    accounts = {c.account: c.scope for c in rows}
    assert accounts['NORTH\\Administrator'] == 'domain north.sevenkingdoms.local'
    assert accounts['.\\Administrator'].startswith('local')
    assert [c.account for c in rows].count('.\\Administrator') == 3
    assert {c.password for c in rows} == {'Aa1234567890!'}


def test_console_spawns_vmware(lab, fake):
    vm_console(lab, 'dc01')
    assert fake.calls[-1][0].endswith('vmware.exe') and fake.calls[-1][1] == lab.vms()['dc01']


def test_vm_start_stop(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, 'Total running VMs: 0\n', ''))
    vm_start(lab, 'dc01')
    assert any(a[3] == 'start' for a in fake.calls)
    vm_stop(lab, 'dc01')
    assert not any(a[3] == 'stop' for a in fake.calls)


def test_unknown_vm(lab):
    with pytest.raises(GoadError, match='no VM named dc09'):
        vm_start(lab, 'dc09')
