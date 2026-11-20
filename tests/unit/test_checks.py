from collections import namedtuple

from goad.cli import Context, main
from goad.host.checks import run_checks
from goad.host.runner import Result

IPCONFIG = '''Windows IP Configuration\r
\r
Ethernet adapter VMware Network Adapter VMnet2:\r
\r
   Connection-specific DNS Suffix  . : \r
   IPv4 Address. . . . . . . . . . . : {ip}\r
   Subnet Mask . . . . . . . . . . . : 255.255.255.0\r
\r
Ethernet adapter VMware Network Adapter VMnet8:\r
\r
   IPv4 Address. . . . . . . . . . . : 192.168.77.1\r
'''
Usage = namedtuple('Usage', 'total used free')
GB = 1024 ** 3


def _checks(fake, settings, ip='192.168.56.1', packer='Packer v1.16.2', free=500 * GB, need_packer=True):
    fake.respond(lambda a: a[0].endswith('ipconfig.exe'), Result(0, IPCONFIG.format(ip=ip), ''))
    fake.respond(lambda a: a[-1] == 'version', Result(0, packer + '\n', ''))
    return {c.name: c for c in run_checks(fake, settings, need_packer,
                                           exists=lambda p: True, disk_usage=lambda p: Usage(0, 0, free),
                                           packer_path=lambda s: '/w/packer.exe')}


def test_vmnet_found(fake, settings):
    assert _checks(fake, settings)['vmnet'].ok


def test_vmnet_missing_gives_fix_hint(fake, settings):
    settings.vmnet = 'VMnet5'
    check = _checks(fake, settings)['vmnet']
    assert not check.ok and 'Virtual Network Editor' in check.detail and 'VMnet5' in check.detail


def test_vmnet_wrong_subnet_fails(fake, settings):
    assert not _checks(fake, settings, ip='192.168.57.1')['vmnet'].ok


def test_packer_too_old(fake, settings):
    assert not _checks(fake, settings, packer='Packer v1.9.4')['packer'].ok


def test_packer_ok_and_skipped(fake, settings):
    assert _checks(fake, settings)['packer'].ok
    assert 'packer' not in _checks(fake, settings, need_packer=False)


def test_disk_too_small(fake, settings):
    assert not _checks(fake, settings, free=50 * GB)['disk'].ok


def _ca_check(fake, settings, files):
    settings.ca_certs_dir = r'C:\certs'
    results = run_checks(fake, settings, False, exists=lambda p: True, disk_usage=lambda p: Usage(0, 0, 500 * GB),
                         packer_path=lambda s: None, cert_files=lambda d: files)
    return {c.name: c for c in results}['ca_certs']


def test_ca_certs_skipped_when_unset(fake, settings):
    assert 'ca_certs' not in _checks(fake, settings)


def test_ca_certs_empty_folder_fails(fake, settings):
    assert not _ca_check(fake, settings, []).ok


def test_ca_certs_found(fake, settings):
    assert _ca_check(fake, settings, ['cato.cer']).ok


def test_check_command_exit_code(monkeypatch):
    from goad.host.checks import Check
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings=None, runner=None))
    monkeypatch.setattr('goad.host.checks.run_checks', lambda *a, **k: [Check('vmrun', True, 'ok')])
    assert main(['check']) == 0
    monkeypatch.setattr('goad.host.checks.run_checks', lambda *a, **k: [Check('vmnet', False, 'missing')])
    assert main(['check']) == 1
