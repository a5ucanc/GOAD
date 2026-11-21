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


def test_destroy_half_deployed(settings, fake):
    save_state(settings, LabState(lab='2domains', ip_range='192.168.56', step='check',
                                  hosts={'dc01': HostState(r'C:\goad\lab\dc01\dc01.vmx', 'win2025-v1', 'kingslanding', '192.168.56.10')}))
    fake.respond(lambda a: a[3] == 'deleteVM', Result(1, 'Error: The file does not exist', ''))
    destroy(settings, fake, yes=True)
    assert any(a[3] == 'deleteVM' for a in fake.calls)
    assert load_state(settings) is None


def test_destroy_empty_hosts(settings, fake):
    save_state(settings, LabState(lab='2domains', ip_range='192.168.56', step='check'))
    destroy(settings, fake, yes=True)
    assert load_state(settings) is None


def test_destroy_rmtree_failure_keeps_state(settings, fake, deployed, local_paths, monkeypatch):
    folders = [local_paths(rf'C:\goad\lab\{h}') for h in ('dc01', 'dc02')]
    for folder in folders:
        folder.mkdir(parents=True)
    tried = []

    def rmtree(path):
        tried.append(path)
        if path == folders[0]:
            raise PermissionError('locked')

    monkeypatch.setattr(lifecycle_module.shutil, 'rmtree', rmtree)
    with pytest.raises(GoadError, match='close VMware and retry') as err:
        destroy(settings, fake, yes=True)
    assert str(folders[0]) in str(err.value)
    assert folders[1] in tried
    assert load_state(settings) is not None


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


def test_creds_laps_row(lab_2forests):
    rows = creds(lab_2forests, laps=lambda ip, pw, host: f'{ip}/{host}')
    row = next(r for r in rows if r.scope == 'local srv03 (LAPS)')
    assert row.password == '192.168.56.12/braavos'
    assert next(r for r in rows if r.scope == 'local srv02').password == 'Aa1234567890!'


def test_creds_laps_unavailable(lab_2forests):
    def fail(*_):
        raise GoadError('no LAPS password for braavos')
    row = next(r for r in creds(lab_2forests, laps=fail) if r.scope.endswith('(LAPS)'))
    assert row.password == 'unavailable: no LAPS password for braavos'


def test_console_spawns_vmware(lab, fake):
    vm_console(lab, 'dc01')
    assert fake.calls[-1][0].endswith('vmware.exe') and fake.calls[-1][1] == lab.vms()['dc01']


def test_vm_start_off(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, 'Total running VMs: 0\n', ''))
    vm_start(lab, 'dc01')
    assert any(a[3] == 'start' for a in fake.calls)


def test_vm_start_running_is_noop(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: 1\n{lab.vms()["dc01"]}\n', ''))
    vm_start(lab, 'dc01')
    assert not any(a[3] == 'start' for a in fake.calls)


def test_vm_stop_running(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: 1\n{lab.vms()["dc01"]}\n', ''))
    vm_stop(lab, 'dc01')
    stops = [a for a in fake.calls if a[3] == 'stop']
    assert len(stops) == 1 and 'hard' not in stops[0]


def test_vm_stop_hard(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: 1\n{lab.vms()["dc01"]}\n', ''))
    vm_stop(lab, 'dc01', hard=True)
    assert [a for a in fake.calls if a[3] == 'stop'][0][-1] == 'hard'


def test_vm_stop_off_is_noop(lab, fake):
    fake.respond(lambda a: a[3] == 'list', Result(0, 'Total running VMs: 0\n', ''))
    vm_stop(lab, 'dc01')
    assert not any(a[3] == 'stop' for a in fake.calls)


def test_unknown_vm(lab):
    with pytest.raises(GoadError, match='no VM named dc09'):
        vm_start(lab, 'dc09')


def test_endpoints_and_creds_use_state_when_definition_lacks_a_host(lab):
    import yaml

    from goad.lab.definition import parse_lab
    from goad.state import working_lab_path
    data = yaml.safe_load(working_lab_path(lab.settings).read_text())
    data['hosts'].pop('srv02')
    lab.definition = parse_lab(yaml.safe_dump(data), 'edited')
    assert lab.endpoints()['srv02'] == ('192.168.56.22', 5985)
    assert [c.scope for c in creds(lab)].count('local srv02') == 1


def test_endpoints_without_definition(lab):
    lab.definition = None
    assert lab.endpoints() == {'dc01': ('192.168.56.10', 5985), 'dc02': ('192.168.56.11', 5985),
                               'srv02': ('192.168.56.22', 5985)}
