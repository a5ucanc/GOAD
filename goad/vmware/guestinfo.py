"""First-boot contract between goad and a template.

goad writes guestinfo.* keys into the clone's .vmx before its first power-on. The template reads them
through VMware Tools, configures itself, and sets guestinfo.goad.firstboot=done when finished.
"""
import base64
import re
from dataclasses import dataclass
from typing import List, Literal, Optional

import yaml

from goad import GoadError
from goad.vmware.vmx import Vmx

FIRSTBOOT_KEY = 'goad.firstboot'
FIRSTBOOT_DONE = 'done'
# a failed first boot sets the marker to 'failed: <message>'
FIRSTBOOT_FAILED = 'failed'
# NetBIOS limit: COMPUTERNAME is cut to 15 characters, and firstboot compares it to this name
_WINDOWS_HOSTNAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,14}$')
# NIC 0 (NAT, internet) uses this adapter type so Linux guests can tell it from the lab NIC
NAT_NIC_DEVICE = 'e1000e'


@dataclass(frozen=True)
class GuestConfig:
    hostname: str
    ip: str
    prefix: int
    gateway: Optional[str]
    dns: List[str]
    admin_password: str
    lab_mac: str


def lab_mac(ip: str) -> str:
    """Static MAC in VMware's manual range 00:50:56:00:00:00-00:50:56:3F:FF:FF, from the last two octets."""
    o3, o4 = (int(part) for part in ip.split('.')[2:4])
    return f'00:50:56:3F:{o3:02X}:{o4:02X}'


def configure_hardware(vmx: Vmx, cpus: int, mem_mb: int, vmnet: str, lab_mac: str) -> None:
    vmx['numvcpus'] = cpus
    vmx['memsize'] = mem_mb
    vmx['ethernet0.present'] = 'TRUE'
    vmx['ethernet0.connectionType'] = 'nat'
    vmx['ethernet0.virtualDev'] = NAT_NIC_DEVICE
    vmx['ethernet0.addressType'] = 'generated'
    vmx['ethernet1.present'] = 'TRUE'
    vmx['ethernet1.connectionType'] = 'custom'
    vmx['ethernet1.vnet'] = vmnet
    vmx['ethernet1.virtualDev'] = 'vmxnet3'
    vmx['ethernet1.addressType'] = 'static'
    vmx['ethernet1.address'] = lab_mac


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _linux_metadata(cfg: GuestConfig) -> str:
    lab = {
        'match': {'macaddress': cfg.lab_mac.lower()},
        'set-name': 'lab',
        'addresses': [f'{cfg.ip}/{cfg.prefix}'],
        'nameservers': {'addresses': list(cfg.dns)},
    }
    if cfg.gateway:
        lab['routes'] = [{'to': 'default', 'via': cfg.gateway}]
    return yaml.safe_dump({
        'instance-id': cfg.hostname,
        'local-hostname': cfg.hostname,
        'network': {'version': 2, 'ethernets': {
            'nat': {'match': {'driver': NAT_NIC_DEVICE}, 'dhcp4': True},
            'lab': lab,
        }},
    }, sort_keys=False)


def _linux_userdata(cfg: GuestConfig) -> str:
    body = yaml.safe_dump({
        'hostname': cfg.hostname,
        'chpasswd': {'expire': False, 'users': [{'name': 'goad', 'password': cfg.admin_password, 'type': 'text'}]},
        'ssh_pwauth': True,
        'runcmd': [f'vmware-rpctool "info-set guestinfo.{FIRSTBOOT_KEY} {FIRSTBOOT_DONE}"'],
    }, sort_keys=False)
    return '#cloud-config\n' + body


def write_guestinfo(vmx: Vmx, cfg: GuestConfig, os_family: Literal['windows', 'linux']) -> None:
    del vmx['guestinfo.' + FIRSTBOOT_KEY]
    if os_family == 'windows':
        if not _WINDOWS_HOSTNAME.match(cfg.hostname):
            raise GoadError(f'invalid Windows hostname {cfg.hostname!r}: 1-15 letters, digits or hyphens, not starting with a hyphen')
        vmx['guestinfo.goad.hostname'] = cfg.hostname
        vmx['guestinfo.goad.ip'] = cfg.ip
        vmx['guestinfo.goad.prefix'] = cfg.prefix
        vmx['guestinfo.goad.gateway'] = cfg.gateway or ''
        vmx['guestinfo.goad.dns'] = ','.join(cfg.dns)
        vmx['guestinfo.goad.password'] = cfg.admin_password
        vmx['guestinfo.goad.mac'] = cfg.lab_mac
    else:
        vmx['guestinfo.metadata'] = _b64(_linux_metadata(cfg))
        vmx['guestinfo.metadata.encoding'] = 'base64'
        vmx['guestinfo.userdata'] = _b64(_linux_userdata(cfg))
        vmx['guestinfo.userdata.encoding'] = 'base64'
