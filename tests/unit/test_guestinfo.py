import base64

import yaml

from goad.vmware.guestinfo import (FIRSTBOOT_KEY, GuestConfig, configure_hardware, lab_mac,
                                   write_guestinfo)
from goad.vmware.vmx import Vmx


def _vmx(tmp_path):
    f = tmp_path / 'a.vmx'
    f.write_text('guestinfo.goad.firstboot = "done"\n')
    return Vmx.load(f)


def _cfg():
    return GuestConfig(hostname='dc01', ip='192.168.56.10', prefix=24, gateway=None,
                       dns=['192.168.56.10', '192.168.56.11'], admin_password='Aa1234567890!',
                       lab_mac=lab_mac('192.168.56.10'))


def test_lab_mac():
    assert lab_mac('192.168.56.10') == '00:50:56:3F:38:0A'


def test_lab_mac_unique_per_ip():
    assert lab_mac('192.168.56.10') != lab_mac('192.168.57.10')


def test_hardware_keys(tmp_path):
    vmx = _vmx(tmp_path)
    configure_hardware(vmx, cpus=2, mem_mb=3072, vmnet='VMnet2', lab_mac='00:50:56:3F:38:0A')
    assert vmx['numvcpus'] == '2' and vmx['memsize'] == '3072'
    assert vmx['ethernet0.connectionType'] == 'nat' and vmx['ethernet0.virtualDev'] == 'e1000e'
    assert vmx['ethernet1.vnet'] == 'VMnet2' and vmx['ethernet1.connectionType'] == 'custom'
    assert vmx['ethernet1.addressType'] == 'static' and vmx['ethernet1.address'] == '00:50:56:3F:38:0A'


def test_windows_guestinfo(tmp_path):
    vmx = _vmx(tmp_path)
    write_guestinfo(vmx, _cfg(), 'windows')
    assert vmx['guestinfo.goad.ip'] == '192.168.56.10'
    assert vmx['guestinfo.goad.dns'] == '192.168.56.10,192.168.56.11'
    assert vmx['guestinfo.goad.mac'] == '00:50:56:3F:38:0A'
    assert vmx['guestinfo.goad.hostname'] == 'dc01'
    assert 'guestinfo.' + FIRSTBOOT_KEY not in vmx


def test_linux_guestinfo_decodes(tmp_path):
    vmx = _vmx(tmp_path)
    write_guestinfo(vmx, _cfg(), 'linux')
    assert vmx['guestinfo.metadata.encoding'] == 'base64'
    meta = yaml.safe_load(base64.b64decode(vmx['guestinfo.metadata']))
    lab = meta['network']['ethernets']['lab']
    assert lab['match']['macaddress'] == '00:50:56:3f:38:0a'
    assert lab['addresses'] == ['192.168.56.10/24']
    assert meta['local-hostname'] == 'dc01'
    user = base64.b64decode(vmx['guestinfo.userdata']).decode()
    assert user.startswith('#cloud-config') and 'info-set guestinfo.goad.firstboot done' in user
    assert 'guestinfo.' + FIRSTBOOT_KEY not in vmx
