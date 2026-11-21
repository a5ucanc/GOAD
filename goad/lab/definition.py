"""Declarative lab definition: labs/<lab>/lab.yml loaded into frozen dataclasses and validated."""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from goad import GoadError
from goad.lab.settings_catalog import GROUP_SCOPES, SETTING_LAYERS, SETTINGS, normalize_value
from goad.settings import OS_NAMES
from goad.templates.smoke import SMOKE_OCTET
from goad.templates.store import OS_FAMILY
from goad.vmware.guestinfo import is_valid_windows_hostname

REPO = Path(__file__).resolve().parents[2]
LAB_NAMES = ('1domain', '2domains', '2forests')
ROLES = ('dc', 'server', 'workstation', 'linux')
_NAME = re.compile(r'^[a-z0-9][a-z0-9-]*$')
_TOP_REQUIRED = {'name', 'password', 'dns_forwarder', 'domains', 'hosts'}
_TOP_KEYS = _TOP_REQUIRED | {'settings'}
_DOMAIN_KEYS = {'netbios', 'dc', 'parent', 'trust', 'ous', 'groups', 'users'}
_DOMAIN_REQUIRED = {'netbios', 'dc'}
_HOST_KEYS = {'hostname', 'os', 'role', 'domain', 'octet', 'cpus', 'memory', 'laps', 'ca', 'local_groups', 'settings'}
_HOST_REQUIRED = {'hostname', 'os', 'role', 'octet', 'cpus', 'memory'}
_GROUP_KEYS = {'scope', 'ou', 'managed_by', 'members'}
_USER_KEYS = {'firstname', 'surname', 'city', 'description', 'ou', 'groups', 'sensitive'}
_USER_REQUIRED = {'firstname', 'surname'}
# AD built-ins a lab may name without defining them (AD names are case-insensitive).
_BUILTIN_GROUPS = frozenset(n.lower() for n in (
    'Administrators', 'Domain Admins', 'Domain Users', 'Domain Computers', 'Domain Controllers', 'Domain Guests',
    'Enterprise Admins', 'Schema Admins', 'Protected Users', 'Account Operators', 'Backup Operators',
    'Server Operators', 'Print Operators', 'Remote Desktop Users', 'Group Policy Creator Owners', 'DnsAdmins'))
_BUILTIN_USERS = frozenset(n.lower() for n in ('Administrator', 'Guest', 'krbtgt'))


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
    laps: bool = False
    ca: bool = False
    local_groups: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    settings: Dict[str, str] = field(default_factory=dict)

    @property
    def family(self) -> str:
        return OS_FAMILY[self.os]


@dataclass(frozen=True)
class GroupDef:
    name: str
    scope: str
    ou: Optional[str] = None
    managed_by: Optional[str] = None
    members: Tuple[str, ...] = ()


@dataclass(frozen=True)
class UserDef:
    name: str
    firstname: str
    surname: str
    city: Optional[str] = None
    description: Optional[str] = None
    ou: Optional[str] = None
    groups: Tuple[str, ...] = ()
    sensitive: bool = False


@dataclass(frozen=True)
class DomainDef:
    name: str
    netbios: str
    dc: str
    parent: Optional[str] = None
    trust: Optional[str] = None
    ous: Tuple[str, ...] = ()
    groups: Dict[str, GroupDef] = field(default_factory=dict)
    users: Dict[str, UserDef] = field(default_factory=dict)


@dataclass(frozen=True)
class LabDef:
    name: str
    password: str
    dns_forwarder: str
    domains: Dict[str, DomainDef]
    hosts: Dict[str, HostDef]
    settings: Dict[str, Dict[str, str]] = field(default_factory=dict)

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

    def effective_settings(self, host: str) -> Dict[str, str]:
        """Layers all, then the host's role layer, then the host's own settings; later wins. Linux hosts get none."""
        h = self.hosts[host]
        if h.family != 'windows':
            return {}
        merged = dict(self.settings.get('all', {}))
        merged.update(self.settings.get(h.role, {}))
        merged.update(h.settings)
        return merged

    def forest_root(self, domain: str) -> str:
        seen = {domain}
        while self.domains[domain].parent:
            domain = self.domains[domain].parent
            if domain in seen:
                raise GoadError(f'parent cycle at domain {domain}')
            seen.add(domain)
        return domain

    def dn(self, domain: str) -> str:
        return ','.join(f'DC={part}' for part in domain.split('.'))

    def trusts(self, domain: str) -> List[str]:
        """Domains trusted in either direction."""
        found = set()
        if self.domains[domain].trust:
            found.add(self.domains[domain].trust)
        found.update(d.name for d in self.domains.values() if d.trust == domain)
        return sorted(found)

    def split_member(self, domain: str, member: str) -> Tuple[str, str]:
        if '\\' in member:
            fqdn, name = member.split('\\', 1)
            return fqdn, name
        return domain, member


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


def _bool(value: Any, source: str, what: str, key: str) -> bool:
    if not isinstance(value, bool):
        raise GoadError(f'{source}: {key!r} in {what} must be a boolean')
    return value


def _opt_str(data: Dict[str, Any], key: str, source: str, what: str) -> Optional[str]:
    return _str(data[key], source, what, key) if key in data else None


def _str_list(value: Any, source: str, what: str, key: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise GoadError(f'{source}: {key!r} in {what} must be a list of non-empty strings')
    return tuple(value)


def _parse_settings(value: Any, source: str, what: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, raw_value in _mapping(value, source, what).items():
        if key not in SETTINGS:
            raise GoadError(f'{source}: unknown setting {key!r} in {what}')
        try:
            text = normalize_value(raw_value, key)
        except TypeError:
            raise GoadError(f'{source}: setting {key!r} in {what} has unsupported value {raw_value!r}')
        accepted = SETTINGS[key][1]
        if text not in accepted:
            raise GoadError(f'{source}: invalid value {raw_value!r} for setting {key!r} in {what}: accepted {", ".join(accepted)}')
        out[key] = text
    return out


def _parse_domain_content(dname: str, d: Dict[str, Any], source: str, what: str):
    ous: Tuple[str, ...] = ()
    if 'ous' in d:
        ous = _str_list(d['ous'], source, what, 'ous')
        dup = next((o for o in ous if ous.count(o) > 1), None)
        if dup is not None:
            raise GoadError(f'{source}: {"ous"!r} in {what} must be unique: {dup!r} repeats')
    groups: Dict[str, GroupDef] = {}
    for gname, g in _mapping(d.get('groups', {}), source, f'groups of {what}').items():
        gwhat = f'group {gname} in {what}'
        g = _mapping(g, source, gwhat)
        _check_keys(g, _GROUP_KEYS, {'scope'}, source, gwhat)
        scope = _str(g['scope'], source, gwhat, 'scope')
        if scope not in GROUP_SCOPES:
            raise GoadError(f'{source}: invalid scope {scope!r} in {gwhat}: choose one of {", ".join(GROUP_SCOPES)}')
        ou = _opt_str(g, 'ou', source, gwhat)
        if ou is not None and ou not in ous:
            raise GoadError(f'{source}: unknown ou {ou!r} in {gwhat}: not in ous of {dname}')
        members = _str_list(g['members'], source, gwhat, 'members') if 'members' in g else ()
        groups[gname] = GroupDef(name=gname, scope=scope, ou=ou, managed_by=_opt_str(g, 'managed_by', source, gwhat), members=members)
    users: Dict[str, UserDef] = {}
    for uname, u in _mapping(d.get('users', {}), source, f'users of {what}').items():
        uwhat = f'user {uname} in {what}'
        u = _mapping(u, source, uwhat)
        _check_keys(u, _USER_KEYS, _USER_REQUIRED, source, uwhat)
        ou = _opt_str(u, 'ou', source, uwhat)
        if ou is not None and ou not in ous:
            raise GoadError(f'{source}: unknown ou {ou!r} in {uwhat}: not in ous of {dname}')
        users[uname] = UserDef(
            name=uname, firstname=_str(u['firstname'], source, uwhat, 'firstname'),
            surname=_str(u['surname'], source, uwhat, 'surname'),
            city=_opt_str(u, 'city', source, uwhat), description=_opt_str(u, 'description', source, uwhat), ou=ou,
            groups=_str_list(u['groups'], source, uwhat, 'groups') if 'groups' in u else (),
            sensitive=_bool(u['sensitive'], source, uwhat, 'sensitive') if 'sensitive' in u else False)
    return ous, groups, users


def parse_lab(text: str, source: str) -> LabDef:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise GoadError(f'{source}: invalid YAML: {e}')
    raw = _mapping(raw, source, 'lab definition')
    _check_keys(raw, _TOP_KEYS, _TOP_REQUIRED, source, 'lab definition')
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
            trust=_str(d['trust'], source, what, 'trust') if 'trust' in d else None,
            **dict(zip(('ous', 'groups', 'users'), _parse_domain_content(dname, d, source, what))))
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
        laps = _bool(h['laps'], source, what, 'laps') if 'laps' in h else False
        ca = _bool(h['ca'], source, what, 'ca') if 'ca' in h else False
        if laps and not (role in ('server', 'workstation') and domain is not None):
            raise GoadError(f'{source}: {"laps"!r} in {what} needs a Windows server or workstation with a domain')
        if ca and not (role in ('dc', 'server') and domain is not None):
            raise GoadError(f'{source}: {"ca"!r} in {what} needs a Windows dc or server with a domain')
        local_groups: Dict[str, Tuple[str, ...]] = {}
        if 'local_groups' in h:
            if role == 'linux':
                raise GoadError(f'{source}: {"local_groups"!r} in {what} is for Windows hosts only')
            for lname, members in _mapping(h['local_groups'], source, f'local_groups of {what}').items():
                local_groups[lname] = _str_list(members, source, what, 'local_groups')
        host_settings = _parse_settings(h['settings'], source, f'settings of {what}') if 'settings' in h else {}
        hosts[hname] = HostDef(
            name=hname, hostname=hostname, os=os_name, role=role, domain=domain, octet=octet, **sizes,
            laps=laps, ca=ca, local_groups=local_groups, settings=host_settings)
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

    layers: Dict[str, Dict[str, str]] = {}
    for layer, values in _mapping(raw.get('settings', {}), source, 'settings').items():
        if layer not in SETTING_LAYERS:
            raise GoadError(f'{source}: unknown settings layer {layer!r}: choose one of {", ".join(SETTING_LAYERS)}')
        layers[layer] = _parse_settings(values, source, f'settings layer {layer}')

    lab = LabDef(name=name, password=password, dns_forwarder=forwarder, domains=domains, hosts=hosts, settings=layers)
    _validate_content(lab, source)
    return lab


def _principals(domain: DomainDef) -> set:
    """Lower-cased names of the users and groups a group member or manager may name in a domain."""
    return {n.lower() for n in (*domain.users, *domain.groups)} | _BUILTIN_USERS | _BUILTIN_GROUPS


def _validate_references(lab: LabDef, source: str) -> None:
    for dname, d in lab.domains.items():
        groups = {n.lower() for n in d.groups} | _BUILTIN_GROUPS
        for uname, u in d.users.items():
            for gname in u.groups:
                if gname.lower() not in groups:
                    raise GoadError(f'{source}: user {uname} in domain {dname} names unknown group {gname!r}: not in groups of {dname} or the AD built-in groups')
        for gname, g in d.groups.items():
            if g.managed_by is not None and g.managed_by.lower() not in _principals(d):
                raise GoadError(f'{source}: group {gname} in domain {dname} has unknown managed_by {g.managed_by!r}: not a user or group of {dname}')
            for member in g.members:
                fqdn, name = lab.split_member(dname, member)
                if fqdn not in lab.domains:
                    raise GoadError(f'{source}: unknown domain {fqdn!r} in member {member!r} of group {gname} in domain {dname}')
                if not name:
                    raise GoadError(f'{source}: member {member!r} of group {gname} in domain {dname} has an empty name')
                if name.lower() not in _principals(lab.domains[fqdn]):
                    raise GoadError(f'{source}: unknown member {member!r} of group {gname} in domain {dname}: not a user or group of {fqdn}')


def _validate_content(lab: LabDef, source: str) -> None:
    _validate_references(lab, source)
    for dname, d in lab.domains.items():
        if d.parent and d.trust:
            raise GoadError(f'{source}: {"trust"!r} in domain {dname} is not allowed on a child domain (has parent)')
        if d.trust and lab.domains[d.trust].parent:
            raise GoadError(f'{source}: {"trust"!r} in domain {dname} names child domain {d.trust}: trust forest roots only')
        for gname, g in d.groups.items():
            for member in g.members:
                fqdn, _ = lab.split_member(dname, member)
                if fqdn not in lab.domains:
                    raise GoadError(f'{source}: unknown domain {fqdn!r} in member {member!r} of group {gname} in domain {dname}')
                if lab.forest_root(fqdn) != lab.forest_root(dname):
                    if g.scope != 'domainlocal':
                        raise GoadError(f'{source}: group {gname} in domain {dname} has member {member!r} from another forest: only domainlocal groups allow that')
                elif fqdn != dname and g.scope == 'global':
                    raise GoadError(f'{source}: group {gname} in domain {dname} has member {member!r} from another domain: global groups allow own-domain members only')
    ca_hosts: Dict[str, str] = {}
    for hname, h in lab.hosts.items():
        if h.ca:
            other = ca_hosts.setdefault(h.domain, hname)
            if other != hname:
                raise GoadError(f'{source}: {"ca"!r} set on host {hname} and host {other} in domain {h.domain}: one CA per domain')
    netbios = {d.netbios.lower() for d in lab.domains.values()}
    for hname, h in lab.hosts.items():
        for lname, members in h.local_groups.items():
            for member in members:
                prefix, sep, rest = member.partition('\\')
                if not sep or not rest or prefix.lower() not in netbios:
                    raise GoadError(f'{source}: {"local_groups"!r} in host {hname}: member {member!r} must be <NETBIOS>\\<name> with a NETBIOS of the lab')
        if h.family != 'windows':
            continue
        for key in lab.effective_settings(hname):
            scope = SETTINGS[key][0]
            if scope == 'dc' and h.role != 'dc':
                raise GoadError(f'{source}: host {hname}: setting {key} applies to DCs only')
            if scope == 'ca' and not h.ca:
                raise GoadError(f'{source}: host {hname}: setting {key} applies to CA hosts only')
