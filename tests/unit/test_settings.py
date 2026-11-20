import pytest

from goad import GoadError
from goad.settings import IsoSource, load_settings, resolve_packer


def test_defaults_without_file(tmp_path):
    s = load_settings(tmp_path / 'missing.yml')
    assert s.vmnet == 'VMnet2' and s.ip_range == '192.168.56'
    assert s.template_root == r'C:\goad\templates'
    assert s.lab_root == r'C:\goad\lab'
    assert s.ca_certs_dir is None
    assert set(s.isos) == {'win2022', 'win2025', 'win11', 'ubuntu2404'}


def test_override_from_yaml(tmp_path):
    f = tmp_path / 'config.yml'
    f.write_text('vmnet: VMnet3\nca_certs_dir: C:\\certs\n')
    s = load_settings(f)
    assert s.vmnet == 'VMnet3' and s.ca_certs_dir == r'C:\certs'


def test_iso_override_merges(tmp_path):
    f = tmp_path / 'config.yml'
    f.write_text('isos:\n  win2025:\n    url: D:\\iso\\2025.iso\n    checksum: none\n')
    s = load_settings(f)
    assert s.isos['win2025'] == IsoSource(url=r'D:\iso\2025.iso', checksum='none')
    assert s.isos['win2022'].url.startswith('https://')


def test_unknown_key_rejected(tmp_path):
    f = tmp_path / 'config.yml'
    f.write_text('foo: 1\n')
    with pytest.raises(GoadError, match='foo'):
        load_settings(f)


def test_unknown_iso_os_rejected(tmp_path):
    f = tmp_path / 'config.yml'
    f.write_text('isos:\n  win7:\n    url: x\n    checksum: none\n')
    with pytest.raises(GoadError, match='win7'):
        load_settings(f)


def test_resolve_packer_prefers_explicit(tmp_path):
    exe = tmp_path / 'packer.exe'
    exe.write_text('')
    assert resolve_packer(str(exe), path_lookup=lambda n: None, winget_glob=lambda: []) == str(exe)


def test_resolve_packer_path_then_winget():
    assert resolve_packer('packer.exe', path_lookup=lambda n: '/usr/bin/packer.exe', winget_glob=lambda: ['/w/packer.exe']) == '/usr/bin/packer.exe'
    assert resolve_packer('packer.exe', path_lookup=lambda n: None, winget_glob=lambda: ['/w/packer.exe']) == '/w/packer.exe'
    assert resolve_packer('packer.exe', path_lookup=lambda n: None, winget_glob=lambda: []) is None


def test_resolve_packer_windows_path(monkeypatch):
    monkeypatch.setattr('os.path.isfile', lambda p: p == '/mnt/c/tools/packer.exe')
    assert resolve_packer(r'C:\tools\packer.exe', path_lookup=lambda n: None, winget_glob=lambda: []) == '/mnt/c/tools/packer.exe'
