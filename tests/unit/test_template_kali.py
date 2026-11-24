import hashlib

import pytest

from goad import GoadError
from goad.cli import build_parser
from goad.host.checks import Check, find_7zip
from goad.host.runner import Result
from goad.templates import kali
from goad.templates.build import build_template
from goad.templates.store import TemplateStore

ARCHIVE = 'kali-linux-2026.3-vmware-amd64.7z'
DATA = b'kali-archive-bytes'
SEVENZIP = '/mnt/c/Program Files/7-Zip/7z.exe'


def test_constants_match_global_constraints():
    assert kali.KALI_URL == 'https://cdimage.kali.org/kali-2026.3/kali-linux-2026.3-vmware-amd64.7z'
    assert kali.KALI_SUMS == 'https://cdimage.kali.org/kali-2026.3/SHA256SUMS'


@pytest.fixture
def store(tmp_path, settings, vmrun):
    root = tmp_path / 'templates'
    root.mkdir()
    return TemplateStore(settings, vmrun, root=root)


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(kali, 'POLL_INTERVAL', 0)
    monkeypatch.setattr(kali, 'find_7zip', lambda: SEVENZIP)


def _cache(store):
    return store.root / '.build' / 'kali'


def _host(store, fake, archive_data=DATA, sums_hash=None):
    """Fake host: curl.exe writes SHA256SUMS and the archive, 7z.exe writes the VM folder, guest commands work."""
    sums_hash = sums_hash or hashlib.sha256(DATA).hexdigest()

    def on_curl(argv):
        if argv[0] != 'curl.exe':
            return False
        _cache(store).mkdir(parents=True, exist_ok=True)
        target = argv[argv.index('-o') + 1]
        if target.endswith('SHA256SUMS'):
            (_cache(store) / 'SHA256SUMS').write_text(f'0000  other.7z\n{sums_hash}  {ARCHIVE}\n')
        else:
            assert target == rf'C:\goad\templates\.build\kali\{ARCHIVE}.part'
            (_cache(store) / f'{ARCHIVE}.part').write_bytes(archive_data)
        return True
    fake.respond(on_curl, Result(0, '', ''))

    def on_extract(argv):
        if argv[0] != SEVENZIP:
            return False
        vm = _cache(store) / 'extract' / 'kali-linux-2026.3-vmware-amd64.vmwarevm'
        vm.mkdir(parents=True)
        (vm / 'kali-linux-2026.3-vmware-amd64.vmx').write_text('displayName = "Kali Linux"\n')
        (vm / 'disk.vmdk').write_text('')
        return True
    fake.respond(on_extract, Result(0, 'Everything is Ok\n', ''))


def _import(settings, fake, store, checks_ok=True):
    return kali.import_kali(settings, fake, store, checks=lambda *a, **k: [Check('7zip', checks_ok, 'x')])


def _verb(call):
    """vmrun command name, after '-T ws' and any -gu/-gp guest credentials."""
    rest = call[3:]
    while rest and rest[0] in ('-gu', '-gp'):
        rest = rest[2:]
    return rest[0] if rest else ''


def test_checksum_mismatch_deletes_archive_and_raises(store, settings, fake):
    _host(store, fake, sums_hash='ab' * 32)
    with pytest.raises(GoadError, match='checksum'):
        _import(settings, fake, store)
    assert not (_cache(store) / ARCHIVE).exists()
    assert not (_cache(store) / f'{ARCHIVE}.part').exists()
    assert not [c for c in fake.calls if c[0] == SEVENZIP]


def test_existing_good_archive_not_downloaded_again(store, settings, fake):
    _host(store, fake)
    _cache(store).mkdir(parents=True)
    (_cache(store) / ARCHIVE).write_bytes(DATA)
    _import(settings, fake, store)
    curls = [c for c in fake.calls if c[0] == 'curl.exe']
    assert len(curls) == 1 and curls[0][-1] == kali.KALI_SUMS


def test_bad_cached_archive_is_downloaded_again(store, settings, fake):
    _host(store, fake)
    _cache(store).mkdir(parents=True)
    (_cache(store) / ARCHIVE).write_bytes(b'truncated')
    _import(settings, fake, store)
    curls = [c for c in fake.calls if c[0] == 'curl.exe']
    assert [c[-1] for c in curls] == [kali.KALI_SUMS, kali.KALI_URL]
    assert all('--ssl-revoke-best-effort' in c for c in curls)
    assert (_cache(store) / ARCHIVE).read_bytes() == DATA


def test_import_runs_extract_guest_copy_guest_run_snapshot_in_order(store, settings, fake):
    _host(store, fake)
    template = _import(settings, fake, store)

    verbs = [_verb(c) if c[0] != SEVENZIP else '7z' for c in fake.calls if c[0] != 'curl.exe']
    order = ['7z', 'start', 'runProgramInGuest', 'copyFileFromHostToGuest', 'runProgramInGuest', 'snapshot']
    assert [v for v in verbs if v in order] == order

    extract = next(c for c in fake.calls if c[0] == SEVENZIP)
    assert extract[1] == 'x' and '-y' in extract
    assert rf'-oC:\goad\templates\.build\kali\extract' in extract
    assert extract[-1] == rf'C:\goad\templates\.build\kali\{ARCHIVE}'

    build_vmx = r'C:\goad\templates\.build\kali-v1\kali-v1.vmx'
    copy = next(c for c in fake.calls if _verb(c) == 'copyFileFromHostToGuest')
    assert copy[3:] == ['-gu', 'kali', '-gp', 'kali', 'copyFileFromHostToGuest', build_vmx,
                        r'C:\goad\templates\.build\kali\kali-prep.sh', '/tmp/kali-prep.sh']
    probe = next(c for c in fake.calls if _verb(c) == 'runProgramInGuest')
    assert probe[3:] == ['-gu', 'kali', '-gp', 'kali', 'runProgramInGuest', build_vmx, '/bin/true']
    run = next(c for c in fake.calls if '/bin/bash' in c)
    assert run[3:] == ['-gu', 'kali', '-gp', 'kali', 'runProgramInGuest', build_vmx,
                       '/bin/bash', '/tmp/kali-prep.sh', 'kali']
    snap = next(c for c in fake.calls if _verb(c) == 'snapshot')
    assert snap[3:] == ['snapshot', r'C:\goad\templates\kali-v1\kali-v1.vmx', 'base']

    assert template.name == 'kali-v1' and template.os == 'kali' and template.version == 1
    assert template.packer_sha == '' and template.vmx == r'C:\goad\templates\kali-v1\kali-v1.vmx'
    final = store.root / 'kali-v1'
    assert (final / 'template.json').is_file() and (final / 'kali-v1.vmx').is_file() and (final / 'disk.vmdk').is_file()
    assert 'displayName = "kali-v1"' in (final / 'kali-v1.vmx').read_text()
    assert not (store.root / '.build' / 'kali-v1').exists()
    assert not (_cache(store) / 'extract').exists()
    assert [t.name for t in store.list()] == ['kali-v1']
    script = (_cache(store) / 'kali-prep.sh').read_bytes()
    assert script.startswith(b'#!/bin/bash\n') and b'\r\n' not in script


def test_second_import_is_next_version(store, settings, fake):
    _host(store, fake)
    _import(settings, fake, store)
    fake.calls.clear()
    template = _import(settings, fake, store)
    assert template.name == 'kali-v2'


def test_waits_for_tools_and_power_off(store, settings, fake):
    _host(store, fake)
    probes = iter([Result(1, '', 'not ready'), Result(1, '', 'not ready'), Result(0, '', '')])
    running = iter(['Total running VMs: 1\nC:\\goad\\templates\\.build\\kali-v1\\kali-v1.vmx\n'] * 2
                   + ['Total running VMs: 0\n'])
    original = fake.run

    def run(argv, timeout=None):
        if _verb(argv) == 'runProgramInGuest' and argv[-1] == '/bin/true':
            fake.calls.append(list(argv))
            return next(probes)
        if argv[3:] == ['list']:
            fake.calls.append(list(argv))
            return Result(0, next(running), '')
        return original(argv, timeout)
    fake.run = run
    _import(settings, fake, store)
    assert len([c for c in fake.calls if c[-1] == '/bin/true']) == 3
    assert len([c for c in fake.calls if c[3:] == ['list']]) == 3


def test_tools_timeout_stops_vm_and_raises(store, settings, fake, monkeypatch):
    fake.respond(lambda a: a[-1] == '/bin/true', Result(1, '', 'not ready'))  # answers before _host's
    _host(store, fake)
    monkeypatch.setattr(kali, 'TOOLS_TIMEOUT', 0)
    with pytest.raises(GoadError, match='VMware Tools') as e:
        _import(settings, fake, store)
    assert 'stop' in [_verb(c) for c in fake.calls]
    assert store.list() == []
    assert str(e.value).endswith(f'the unfinished VM (several GB) is kept in {settings.template_root}\\.build\\kali-v1: '
                                 'delete that folder and run goad template import kali again')


def test_failed_checks_stop_before_download(store, settings, fake):
    _host(store, fake)
    with pytest.raises(GoadError, match='host checks failed'):
        _import(settings, fake, store, checks_ok=False)
    assert fake.calls == []


def test_missing_7zip(store, settings, fake, monkeypatch):
    monkeypatch.setattr(kali, 'find_7zip', lambda: None)
    _host(store, fake)
    with pytest.raises(GoadError, match='7-Zip not found: winget install 7zip.7zip'):
        _import(settings, fake, store)


def test_find_7zip_prefers_path():
    assert find_7zip(path_lookup=lambda name: '/x/7z.exe', exists=lambda p: True) == '/x/7z.exe'
    assert find_7zip(path_lookup=lambda name: None, exists=lambda p: True) == SEVENZIP
    assert find_7zip(path_lookup=lambda name: None, exists=lambda p: False) is None


def test_build_kali_refuses(store, settings, fake):
    with pytest.raises(GoadError, match='kali is imported, not built: run goad template import kali'):
        build_template('kali', settings, fake, store, checks=lambda *a, **k: [], packer_path=lambda s: 'p')
    assert fake.calls == []


def test_cli_template_import_kali(monkeypatch):
    args = build_parser().parse_args(['template', 'import', 'kali'])
    assert args.command == ('template', 'import') and args.os == 'kali'
    with pytest.raises(SystemExit):
        build_parser().parse_args(['template', 'import', 'ubuntu2404'])


def test_prep_script_contents():
    text = kali.PREP_SCRIPT.read_text()
    for needed in ('cloud-init', 'openssh-server', 'sudo -S', 'datasource_list: [ VMware, None ]',
                   'network-manager', 'NOPASSWD:ALL', 'systemctl enable ssh', 'truncate -s 0 /etc/machine-id',
                   'rm -f /etc/ssh/ssh_host_*', 'cloud-init clean --logs --seed', 'poweroff'):
        assert needed in text, needed


def test_cli_build_and_test_accept_kali():
    # build reaches build_template, which refuses with the import hint; test smoke-tests the imported template
    assert build_parser().parse_args(['template', 'build', 'kali']).os == 'kali'
    assert build_parser().parse_args(['template', 'test', 'kali']).os == 'kali'


def test_ca_certs_copied_into_guest_before_prep(store, settings, fake, tmp_path):
    _host(store, fake)
    settings.ca_certs_dir = r'C:\certs'
    kali.import_kali(settings, fake, store, checks=lambda *a, **k: [],
                     cert_files=lambda folder: [tmp_path / 'Corp Root.cer', tmp_path / 'b.crt'])
    guest = [c[9:] for c in fake.calls if _verb(c) in ('copyFileFromHostToGuest', 'runProgramInGuest')]
    assert guest == [['/bin/true'],
                     [r'C:\goad\templates\.build\kali\kali-prep.sh', '/tmp/kali-prep.sh'],
                     [r'C:\certs\Corp Root.cer', '/tmp/goad-ca-0.cer'],
                     [r'C:\certs\b.crt', '/tmp/goad-ca-1.crt'],
                     ['/bin/bash', '/tmp/kali-prep.sh', 'kali']]
    assert '/tmp/goad-ca-' in kali.PREP_SCRIPT.read_text() and 'update-ca-certificates' in kali.PREP_SCRIPT.read_text()


def test_prep_waits_for_network_and_dpkg_lock():
    text = kali.PREP_SCRIPT.read_text()
    assert text.index('nm-online') < text.index('apt-get update')
    assert text.count('DPkg::Lock::Timeout=300') == 2
    assert text.index('mkdir -p /usr/local/share/ca-certificates') < text.index('for cert in /tmp/goad-ca-*')


def _locked_rename(monkeypatch, store, failures):
    """Path.rename of .build\\kali-v1 fails `failures` times, as a Windows lock right after power-off would."""
    import pathlib
    real = pathlib.Path.rename
    left = [failures]

    def rename(self, target):
        if self == store.root / '.build' / 'kali-v1' and left[0] > 0:
            left[0] -= 1
            raise PermissionError(13, 'Permission denied', str(self))
        return real(self, target)
    monkeypatch.setattr(pathlib.Path, 'rename', rename)
    monkeypatch.setattr(kali, 'RENAME_DELAY', 0)


def test_final_move_retries_a_windows_lock(store, settings, fake, monkeypatch):
    _host(store, fake)
    _locked_rename(monkeypatch, store, failures=2)
    assert _import(settings, fake, store).name == 'kali-v1'
    assert (store.root / 'kali-v1' / 'template.json').is_file()


def test_final_move_gives_up_naming_build_path(store, settings, fake, monkeypatch):
    _host(store, fake)
    _locked_rename(monkeypatch, store, failures=99)
    with pytest.raises(GoadError, match=r'C:\\goad\\templates\\\.build\\kali-v1'):
        _import(settings, fake, store)
    assert store.list() == []
    assert 'snapshot' not in [_verb(c) for c in fake.calls]
