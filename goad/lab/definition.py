"""Declarative lab definition: labs/<lab>/lab.yml loaded into frozen dataclasses and validated."""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from goad import GoadError
from goad.settings import OS_NAMES
from goad.templates.smoke import SMOKE_OCTET
from goad.templates.store import OS_FAMILY
from goad.vmware.guestinfo import is_valid_windows_hostname

REPO = Path(__file__).resolve().parents[2]
LAB_NAMES = ('1domain', '2domains', '2forests')
ROLES = ('dc', 'server', 'workstation', 'linux')
_NAME = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_TOP_KEYS = {'name', 'password', 'dns_forwarder', 'domains', 'hosts'}
_DOMAIN_KEYS = {'netbios', 'dc', 'parent', 'trust'}
_DOMAIN_REQUIRED = {'netbios', 'dc'}
_HOST_KEYS = {'hostname', 'os', 'role', 'domain', 'octet', 'cpus', 'memory'}
_HOST_REQUIRED = _HOST_KEYS - {'domain'}


@dataclass(frozen=True)
class HostDef:
    name: str
    hostname: str
    os: str
    role: str
    domain: Optional[str]
    octet: int
    cpus: int
    memory: int

    @property
    def family(self) -> str:
        return OS_FAMILY[self.os]


@dataclass(frozen=True)
class DomainDef:
    name: str
    netbios: str
    dc: str
    parent: Optional[str] = None
    trust: Optional[str] = None


@dataclass(frozen=True)
class LabDef:
    name: str
    password: str
    dns_forwarder: str
    domains: Dict[str, DomainDef]
    hosts: Dict[str, HostDef]

    def ip(self, host: str, ip_range: str) -> str:
        return f'{ip_range}.{self.hosts[host].octet}'

    def dns(self, host: str, ip_range: str) -> List[str]:
        """First-boot DNS: parent DC for a child domain's DC, else the host's domain DC, else the first domain's DC."""
        h = self.hosts[host]
        if h.domain is None:
            domain = next(iter(self.domains.values()))
        else:
            domain = self.domains[h.domain]
            if h.role == 'dc' and domain.parent:
                domain = self.domains[domain.parent]
        return [self.ip(domain.dc, ip_range)]

    def templates_needed(self) -> List[str]:
        return sorted({h.os for h in self.hosts.values()})


def shipped_lab(name: str) -> Path:
    if name not in LAB_NAMES:
        raise GoadError(f'unknown lab {name!r}: choose one of {", ".join(LAB_NAMES)}')
    return REPO / 'labs' / name / 'lab.yml'


def load_lab(path: Path) -> LabDef:
    try:
        text = Path(path).read_text()
    except OSError as e:
        raise GoadError(f'cannot read lab definition {path}: {e}')
    return parse_lab(text, str(path))


def _mapping(value: Any, source: str, what: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise GoadError(f'{source}: {what} must be a mapping')
    return value


def _check_keys(data: Dict[str, Any], allowed: set, required: set, source: str, what: str) -> None:
    for key in data:
        if key not in allowed:
            raise GoadError(f'{source}: unknown key {key!r} in {what}')
    for key in sorted(required):
        if key not in data:
            raise GoadError(f'{source}: missing key {key!r} in {what}')


def _int(value: Any, source: str, what: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoadError(f'{source}: {key!r} in {what} must be an integer')
    return value


def _str(value: Any, source: str, what: str, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise GoadError(f'{source}: {key!r} in {what} must be a non-empty string')
    return value


def parse_lab(text: str, source: str) -> LabDef:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GoadError(f'{source}: invalid YAML: {e}')
    raw = _mapping(raw, source, 'lab definition')
    _check_keys(raw, _TOP_KEYS, _TOP_KEYS, source, 'lab definition')
    name = _str(raw['name'], source, 'lab definition', 'name')
    if not _NAME.match(name):
        raise GoadError(f'{source}: invalid name {name!r}: lowercase letters, digits and hyphens, not starting with a hyphen')
    password = _str(raw['password'], source, 'lab definition', 'password')
    forwarder = _str(raw['dns_forwarder'], source, 'lab definition', 'dns_forwarder')

    domains: Dict[str, DomainDef] = {}
    for dname, d in _mapping(raw['domains'], source, 'domains').items():
        what = f'domain {dname}'
        d = _mapping(d, source, what)
        _check_keys(d, _DOMAIN_KEYS, _DOMAIN_REQUIRED, source, what)
        domains[dname] = DomainDef(
            name=dname,
            netbios=_str(d['netbios'], source, what, 'netbios'),
            dc=_str(d['dc'], source, what, 'dc'),
            parent=_str(d['parent'], source, what, 'parent') if 'parent' in d else None,
            trust=_str(d['trust'], source, what, 'trust') if 'trust' in d else None)
    if not domains:
        raise GoadError(f'{source}: domains must not be empty')

    hosts: Dict[str, HostDef] = {}
    for hname, h in _mapping(raw['hosts'], source, 'hosts').items():
        what = f'host {hname}'
        h = _mapping(h, source, what)
        _check_keys(h, _HOST_KEYS, _HOST_REQUIRED, source, what)
        os_name = _str(h['os'], source, what, 'os')
        if os_name not in OS_NAMES:
            raise GoadError(f'{source}: unknown os {os_name!r} in {what}: choose one of {", ".join(OS_NAMES)}')
        role = _str(h['role'], source, what, 'role')
        if role not in ROLES:
            raise GoadError(f'{source}: unknown role {role!r} in {what}: choose one of {", ".join(ROLES)}')
        if (role == 'linux') != (OS_FAMILY[os_name] == 'linux'):
            raise GoadError(f'{source}: role {role!r} does not match os {os_name!r} in {what}: role linux is for Linux os only')
        hostname = _str(h['hostname'], source, what, 'hostname')
        if OS_FAMILY[os_name] == 'windows' and not is_valid_windows_hostname(hostname):
            raise GoadError(f'{source}: invalid Windows hostname {hostname!r} in {what}: 1-15 letters, digits or hyphens, not starting with a hyphen')
        domain = _str(h['domain'], source, what, 'domain') if 'domain' in h else None
        if domain is not None and domain not in domains:
            raise GoadError(f'{source}: unknown domain {domain!r} in {what}')
        octet = _int(h['octet'], source, what, 'octet')
        if not 2 <= octet <= 254 or octet == SMOKE_OCTET:
            raise GoadError(f'{source}: invalid octet {octet} in {what}: use 2-254, not {SMOKE_OCTET} (reserved for template test)')
        sizes = {}
        for key in ('cpus', 'memory'):
            sizes[key] = _int(h[key], source, what, key)
            if sizes[key] < 1:
                raise GoadError(f'{source}: {key!r} in {what} must be at least 1')
        hosts[hname] = HostDef(
            name=hname, hostname=hostname, os=os_name, role=role, domain=domain, octet=octet, **sizes)
    if not hosts:
        raise GoadError(f'{source}: hosts must not be empty')

    seen_names: Dict[str, str] = {}
    seen_octets: Dict[int, str] = {}
    for hname, h in hosts.items():
        other = seen_names.setdefault(h.hostname.lower(), hname)
        if other != hname:
            raise GoadError(f'{source}: duplicate hostname {h.hostname!r} in host {hname} and host {other}')
        other = seen_octets.setdefault(h.octet, hname)
        if other != hname:
            raise GoadError(f'{source}: duplicate octet {h.octet} in host {hname} and host {other}')

    for dname, d in domains.items():
        dc = hosts.get(d.dc)
        if dc is None or dc.role != 'dc' or dc.domain != dname:
            raise GoadError(f'{source}: dc {d.dc!r} of domain {dname} must be a host with role dc and domain {dname}')
        for key, ref in (('parent', d.parent), ('trust', d.trust)):
            if ref is not None and ref not in domains:
                raise GoadError(f'{source}: unknown domain {ref!r} in {key} of domain {dname}')
    for hname, h in hosts.items():
        if h.role == 'dc' and (h.domain is None or domains[h.domain].dc != hname):
            raise GoadError(f'{source}: host {hname} has role dc but is not the dc of its domain')

    return LabDef(name=name, password=password, dns_forwarder=forwarder, domains=domains, hosts=hosts)
