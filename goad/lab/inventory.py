"""Ansible inventory generated from a lab definition."""
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from goad.lab.definition import WELL_KNOWN_PRINCIPALS, AclDef, DelegationDef, HostDef, LabDef, UserDef
from goad.settings import Settings
from goad.state import inventory_path


def _delegation(d: DelegationDef) -> Dict[str, Any]:
    return {'unconstrained': d.unconstrained, 'constrained': list(d.constrained),
            'protocol_transition': d.protocol_transition}


def _user(u: UserDef, path: str) -> Dict[str, Any]:
    """Keys added for scenarios are emitted only when not at their default, so older inventories stay unchanged."""
    e: Dict[str, Any] = {'firstname': u.firstname, 'surname': u.surname, 'city': u.city,
                         'description': u.description, 'path': path, 'groups': list(u.groups),
                         'sensitive': u.sensitive}
    if u.password is not None:
        e['password'] = u.password
    if u.spns:
        e['spns'] = list(u.spns)
    if not u.preauth:
        e['preauth'] = False
    if u.delegation is not None:
        e['delegation'] = _delegation(u.delegation)
    return e


def _qualified(lab: LabDef, fqdn: str, principal: str) -> str:
    """<NETBIOS>\\<name> for a lab principal (bare names belong to fqdn); a well-known name as is."""
    if principal in WELL_KNOWN_PRINCIPALS:
        return principal
    dom, name = lab.split_member(fqdn, principal)
    return f'{lab.domains[dom].netbios}\\{name}'


def _adcs(lab: LabDef, h: HostDef) -> Dict[str, Any]:
    """cert_templates and ca_acl of a CA host, each only when set, so older inventories stay unchanged."""
    e: Dict[str, Any] = {}
    if h.cert_templates:
        e['cert_templates'] = {
            name: {'json': t.json, 'builtin': t.builtin, 'enroll': [_qualified(lab, h.domain, p) for p in t.enroll],
                   'issuance_group': t.issuance_group}
            for name, t in h.cert_templates.items()}
    if h.ca_acl:
        e['ca_acl'] = [{'principal': _qualified(lab, h.domain, p), 'right': r} for p, r in h.ca_acl]
    return e


def _acl(lab: LabDef, fqdn: str, a: AclDef) -> Dict[str, Any]:
    """An ACE as ace.ps1 takes it: a principal another domain owns as <NETBIOS>\\<name>, which LSA
    resolves across trusts, and a computer by its sAMAccountName."""
    principal = a.principal
    if principal not in WELL_KNOWN_PRINCIPALS and '\\' in principal:
        dom, name = lab.split_member(fqdn, principal)
        principal = f'{lab.domains[dom].netbios}\\{name}'
    name = a.target
    if a.kind == 'computer':
        name = f'{lab.hosts[name].hostname}$'
    return {'principal': principal, 'right': a.right, 'inherit': a.inherit, 'kind': a.kind, 'name': name}


def _domains(lab: LabDef, ip_range: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for fqdn, d in lab.domains.items():
        dn = lab.dn(fqdn)
        root = lab.forest_root(fqdn)

        def path(ou: Optional[str]) -> str:
            return f'OU={ou},{dn}' if ou else f'CN=Users,{dn}'

        groups = {}
        for gname, g in d.groups.items():
            members = [{'name': name, 'domain': dom} for dom, name in (lab.split_member(fqdn, m) for m in g.members)]
            groups[gname] = {'scope': g.scope, 'path': path(g.ou), 'managed_by': g.managed_by,
                             'members': members}
            if g.groups:
                groups[gname]['member_of'] = list(g.groups)
        users = {uname: _user(u, path(u.ou)) for uname, u in d.users.items()}
        dc = lab.hosts[d.dc]
        out[fqdn] = {
            'netbios': d.netbios, 'dn': dn, 'dc': d.dc, 'dc_hostname': f'{dc.hostname}.{fqdn}',
            'dc_ip': lab.ip(d.dc, ip_range), 'parent': d.parent, 'forest_root': root, 'trust': d.trust,
            'trusts': lab.trusts(fqdn), 'ous': list(d.ous), 'groups': groups, 'users': users,
            'laps_hosts': [h.hostname for h in lab.hosts.values() if h.laps and h.domain == fqdn]}
        computers = {h.hostname: _delegation(h.delegation) for h in lab.hosts.values()
                     if h.delegation is not None and h.domain == fqdn}
        if computers:
            out[fqdn]['computers'] = computers
        if d.gpos:
            out[fqdn]['gpos'] = {name: {'link': g.link} for name, g in d.gpos.items()}
        if d.acls:
            out[fqdn]['acls'] = [_acl(lab, fqdn, a) for a in d.acls]
    return out


def render_inventory(lab: LabDef, ip_range: str) -> Dict[str, Any]:
    def entry(name: str) -> Dict[str, Any]:
        h = lab.hosts[name]
        e: Dict[str, Any] = {'ansible_host': lab.ip(name, ip_range), 'hostname': h.hostname, 'domain': h.domain,
                             'netbios': lab.domains[h.domain].netbios if h.domain else None,
                             'goad_settings': lab.effective_settings(name), 'laps': h.laps, 'ca': h.ca,
                             'local_groups': {g: list(m) for g, m in h.local_groups.items()}}
        e.update(_adcs(lab, h))
        if h.services:
            e['services'] = {name: dict(config) for name, config in h.services.items()}
        if h.role == 'dc':
            domain = lab.domains[h.domain]
            own = lab.ip(name, ip_range)
            if domain.parent:
                parent_dc = lab.ip(lab.domains[domain.parent].dc, ip_range)
                e['dc_dns'] = [own, parent_dc]
                e['dc_forwarder'] = parent_dc
                e['laps_schema'] = False
            else:
                e['dc_dns'] = [own]
                e['dc_forwarder'] = lab.dns_forwarder
                e['laps_schema'] = any(x.laps and x.domain and lab.forest_root(x.domain) == h.domain
                                       for x in lab.hosts.values())
        elif h.role in ('server', 'workstation') and h.domain:
            e['ansible_user'] = f'{lab.domains[h.domain].netbios}\\Administrator'
            e['local_user'] = 'Administrator'
        return e

    def group(members: list) -> Dict[str, Any]:
        return {'hosts': {name: entry(name) for name in members}}

    names = list(lab.hosts)
    windows = [n for n in names if lab.hosts[n].family == 'windows']
    linux = [n for n in names if lab.hosts[n].family == 'linux']
    dcs = [n for n in names if lab.hosts[n].role == 'dc']
    children: Dict[str, Any] = {
        'windows': {**group(windows), 'vars': {'ansible_connection': 'psrp', 'ansible_psrp_auth': 'ntlm',
                                               'ansible_psrp_protocol': 'http'}},
        'linux': {**group(linux), 'vars': {'ansible_connection': 'ssh', 'ansible_user': 'goad'}},
    }
    for role in ('dc', 'server', 'workstation'):
        children[role] = group([n for n in names if lab.hosts[n].role == role])
    children['forest_root'] = group([n for n in dcs if not lab.domains[lab.hosts[n].domain].parent])
    children['child_dc'] = group([n for n in dcs if lab.domains[lab.hosts[n].domain].parent])
    children['member'] = group([n for n in names if lab.hosts[n].role in ('server', 'workstation')
                                and lab.hosts[n].domain])
    all_vars: Dict[str, Any] = {'ansible_user': 'Administrator', 'ansible_password': lab.password, 'lab_name': lab.name,
                                'dns_forwarder': lab.dns_forwarder, 'lab_password': lab.password,
                                'goad_domains': _domains(lab, ip_range)}
    if lab.extensions:
        all_vars['goad_extensions'] = list(lab.extensions)
    return {'all': {'vars': all_vars, 'children': children}}


def write_inventory(settings: Settings, lab: LabDef, ip_range: str) -> Path:
    path = inventory_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(render_inventory(lab, ip_range), sort_keys=False))
    return path
