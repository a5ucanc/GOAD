import copy

import pytest
import yaml

from goad import GoadError
from goad.lab import scenarios
from goad.lab.definition import LAB_NAMES, ScenarioRef, load_lab, parse_lab, shipped_lab


def test_shipped_labs_load():
    for name in LAB_NAMES:
        lab = load_lab(shipped_lab(name))
        assert lab.name == name and lab.password == 'Aa1234567890!'


def test_2forests_host_map():
    lab = load_lab(shipped_lab('2forests'))
    assert {h: (d.hostname, d.octet, d.os) for h, d in lab.hosts.items()} == {
        'dc01': ('kingslanding', 10, 'win2025'), 'dc02': ('winterfell', 11, 'win2025'),
        'dc03': ('meereen', 12, 'win2025'), 'srv02': ('castelblack', 22, 'win2022'),
        'srv03': ('braavos', 23, 'win2022')}
    assert lab.domains['essos.local'].trust == 'sevenkingdoms.local'
    assert lab.templates_needed() == ['win2022', 'win2025']


def test_ip_and_dns():
    lab = load_lab(shipped_lab('2domains'))
    assert lab.ip('srv02', '10.0.5') == '10.0.5.22'
    assert lab.dns('dc01', '10.0.5') == ['10.0.5.10']
    assert lab.dns('dc02', '10.0.5') == ['10.0.5.10']   # child DC points at the parent DC
    assert lab.dns('srv02', '10.0.5') == ['10.0.5.11']


def test_unknown_shipped_lab_rejected():
    with pytest.raises(GoadError, match='nope'):
        shipped_lab('nope')


@pytest.mark.parametrize('mutate, message', [
    (lambda d: d['hosts']['srv02'].update(octet=10), 'octet'),
    (lambda d: d['hosts']['srv02'].update(octet=250), 'octet'),
    (lambda d: d['hosts']['srv02'].update(hostname='castelblack-north'), 'hostname'),
    (lambda d: d['hosts']['srv02'].update(hostname='KINGSLANDING'), 'hostname'),
    (lambda d: d['hosts']['srv02'].update(os='win10'), 'os'),
    (lambda d: d['hosts']['srv02'].update(role='linux'), 'role'),
    (lambda d: d['hosts']['srv02'].update(domain='nope.local'), 'domain'),
    (lambda d: d['hosts']['srv02'].update(colour='red'), 'colour'),
    (lambda d: d['hosts']['srv02'].pop('octet'), 'octet'),
    (lambda d: d['hosts']['srv02'].update(role='dc'), 'dc'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(dc='srv02'), 'dc'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(parent='nope.local'), 'parent'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(trust='nope.local'), 'trust'),
    (lambda d: d.update(name='Two Domains'), 'name'),
    (lambda d: d.update(extra=1), 'extra'),
    (lambda d: d.pop('password'), 'password'),
])
def test_invalid_lab_rejected(mutate, message):
    data = yaml.safe_load(shipped_lab('2domains').read_text())
    mutate(data)
    with pytest.raises(GoadError, match=message):
        parse_lab(yaml.safe_dump(data), 'lab.yml')


@pytest.mark.parametrize('key, value', [('cpus', 0), ('cpus', -1), ('memory', 0)])
def test_sizes_must_be_positive(key, value):
    data = yaml.safe_load(shipped_lab('2domains').read_text())
    data['hosts']['srv02'][key] = value
    with pytest.raises(GoadError, match=f"'{key}' in host srv02 must be at least 1"):
        parse_lab(yaml.safe_dump(data), 'lab.yml')


BASE = {
    'name': '2forests', 'password': 'Aa1234567890!', 'dns_forwarder': '1.1.1.1',
    'domains': {
        'sevenkingdoms.local': {'netbios': 'SEVENKINGDOMS', 'dc': 'dc01'},
        'north.sevenkingdoms.local': {'netbios': 'NORTH', 'dc': 'dc02', 'parent': 'sevenkingdoms.local'},
        'essos.local': {'netbios': 'ESSOS', 'dc': 'dc03', 'trust': 'sevenkingdoms.local',
                        'groups': {'Dothraki': {'scope': 'global'}}},
    },
    'hosts': {
        'dc01': {'hostname': 'kingslanding', 'os': 'win2025', 'role': 'dc', 'domain': 'sevenkingdoms.local', 'octet': 10, 'cpus': 2, 'memory': 4096},
        'dc02': {'hostname': 'winterfell', 'os': 'win2025', 'role': 'dc', 'domain': 'north.sevenkingdoms.local', 'octet': 11, 'cpus': 2, 'memory': 4096},
        'dc03': {'hostname': 'meereen', 'os': 'win2025', 'role': 'dc', 'domain': 'essos.local', 'octet': 12, 'cpus': 2, 'memory': 4096},
        'srv02': {'hostname': 'castelblack', 'os': 'win2022', 'role': 'server', 'domain': 'north.sevenkingdoms.local', 'octet': 22, 'cpus': 2, 'memory': 4096},
        'srv03': {'hostname': 'braavos', 'os': 'win2022', 'role': 'server', 'domain': 'essos.local', 'octet': 23, 'cpus': 2, 'memory': 4096,
                  'laps': True, 'ca': True},
    },
}


def _lab(*patches):  # each patch: (key path tuple, value); domain names contain dots
    data = copy.deepcopy(BASE)
    for path, value in patches:
        target = data
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return parse_lab(yaml.safe_dump(data), 'lab.yml')


ESSOS = ('domains', 'essos.local')
SRV02 = ('hosts', 'srv02')
SRV03 = ('hosts', 'srv03')
LINUX = {'hostname': 'lnx', 'os': 'ubuntu2404', 'role': 'linux', 'octet': 30, 'cpus': 1, 'memory': 1024}


def test_base_loads():
    lab = _lab()
    assert lab.hosts['srv03'].laps and lab.hosts['srv03'].ca
    assert lab.domains['essos.local'].groups['Dothraki'].scope == 'global'


def test_yaml_booleans_normalized():
    lab = _lab((('settings', 'all'), {'defender.realtime': True}),
               (SRV03 + ('settings',), {'adcs.web_enrollment': False}))
    assert lab.effective_settings('srv02')['defender.realtime'] == 'on'
    assert lab.effective_settings('srv03')['adcs.web_enrollment'] == 'off'


def test_boolean_not_accepted():
    with pytest.raises(GoadError, match=r"smb.signing.*required, optional"):
        _lab((('settings', 'all'), {'smb.signing': True}))


def test_dc_setting_in_all_layer_refused():
    with pytest.raises(GoadError, match=r'host srv02: setting dc.maq applies to DCs only'):
        _lab((('settings', 'all'), {'dc.maq': 0}))


def test_ca_setting_needs_ca_host():
    with pytest.raises(GoadError, match=r'host srv02: setting adcs.editf_san'):
        _lab((SRV02 + ('settings',), {'adcs.editf_san': 'off'}))


def test_cross_forest_member_needs_domainlocal():
    with pytest.raises(GoadError, match=r'group Dothraki'):
        _lab((ESSOS + ('groups', 'Dothraki', 'members'), ['sevenkingdoms.local\\tywin.lannister']))


def test_layering_and_helpers():
    lab = _lab()
    assert lab.forest_root('north.sevenkingdoms.local') == 'sevenkingdoms.local'
    assert lab.forest_root('essos.local') == 'essos.local'
    assert lab.dn('north.sevenkingdoms.local') == 'DC=north,DC=sevenkingdoms,DC=local'
    assert lab.trusts('sevenkingdoms.local') == ['essos.local']
    assert lab.trusts('essos.local') == ['sevenkingdoms.local']
    assert lab.trusts('north.sevenkingdoms.local') == []
    assert lab.split_member('essos.local', 'Dragons') == ('essos.local', 'Dragons')
    assert lab.split_member('essos.local', 'north.sevenkingdoms.local\\arya') == ('north.sevenkingdoms.local', 'arya')


def test_effective_settings_layer_order():
    lab = _lab((('settings', 'all'), {'ntlm.lmcompat': 5, 'host.tier': 2}),
               (('settings', 'dc'), {'host.tier': 0, 'dc.maq': 0}),
               (('settings', 'server'), {'host.tier': 1}),
               (SRV03 + ('settings',), {'ntlm.lmcompat': 3}))
    assert lab.effective_settings('dc01') == {'ntlm.lmcompat': '5', 'host.tier': '0', 'dc.maq': '0'}
    assert lab.effective_settings('srv02') == {'ntlm.lmcompat': '5', 'host.tier': '1'}
    assert lab.effective_settings('srv03')['ntlm.lmcompat'] == '3'


def test_effective_settings_linux_empty():
    lab = _lab((('settings', 'all'), {'ntlm.lmcompat': 5}), (('hosts', 'lnx'), LINUX))
    assert lab.effective_settings('lnx') == {}


def test_valid_content_loads():
    lab = _lab(
        (ESSOS + ('ous',), ['Vale', 'Dorne']),
        (ESSOS + ('groups', 'Dothraki'), {'scope': 'global', 'ou': 'Vale', 'managed_by': 'khal.drogo'}),
        (ESSOS + ('groups', 'DragonsFriends'), {
            'scope': 'domainlocal', 'members': ['daenerys.targaryen', 'sevenkingdoms.local\\tyron.lannister']}),
        (ESSOS + ('users', 'khal.drogo'), {'firstname': 'Khal', 'surname': 'Drogo', 'city': 'Vaes Dothrak',
                                           'description': 'Khal Drogo', 'groups': ['Dothraki'], 'ou': 'Dorne'}),
        (ESSOS + ('users', 'daenerys.targaryen'), {'firstname': 'D', 'surname': 'T', 'sensitive': True}),
        (('domains', 'sevenkingdoms.local', 'users', 'tyron.lannister'), {'firstname': 'T', 'surname': 'L'}),
        (SRV03 + ('local_groups',), {'Administrators': ['ESSOS\\T1-ServerAdmins', 'north\\x']}))
    d = lab.domains['essos.local']
    assert d.ous == ('Vale', 'Dorne')
    assert d.groups['DragonsFriends'].members == ('daenerys.targaryen', 'sevenkingdoms.local\\tyron.lannister')
    assert d.users['khal.drogo'].groups == ('Dothraki',) and d.users['daenerys.targaryen'].sensitive
    assert lab.hosts['srv03'].local_groups == {'Administrators': ('ESSOS\\T1-ServerAdmins', 'north\\x')}


def test_same_forest_member_in_universal_group_ok():
    lab = _lab((('domains', 'sevenkingdoms.local', 'groups', 'G'),
                {'scope': 'universal', 'members': ['north.sevenkingdoms.local\\a']}),
               (('domains', 'north.sevenkingdoms.local', 'users', 'a'), {'firstname': 'A', 'surname': 'A'}))
    assert lab.domains['sevenkingdoms.local'].groups['G'].scope == 'universal'


def test_plan2_lab_yml_still_loads():
    text = ('name: x\npassword: p\ndns_forwarder: 1.1.1.1\ndomains: {a.local: {netbios: A, dc: dc01}}\n'
            'hosts: {dc01: {hostname: dc, os: win2025, role: dc, domain: a.local, octet: 10, cpus: 2, memory: 4096}}\n')
    lab = parse_lab(text, 'lab.yml')
    assert lab.domains['a.local'].users == {} and lab.effective_settings('dc01') == {}


G = ESSOS + ('groups', 'Dothraki')


@pytest.mark.parametrize('patches, message', [
    ([(ESSOS + ('groups', 'X'), {})], "missing key 'scope'"),
    ([(G + ('colour',), 'red')], "unknown key 'colour'"),
    ([(ESSOS + ('users', 'u'), {'surname': 'S'})], "missing key 'firstname'"),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F'})], "missing key 'surname'"),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F', 'surname': 'S', 'age': 3})], "unknown key 'age'"),
    ([(('settings', 'everyone'), {})], 'everyone'),
    ([(('settings', 'all'), 'x')], 'settings'),
    ([(ESSOS + ('ous',), 'Vale')], 'ous'),
    ([(ESSOS + ('ous',), ['Vale', 'Vale'])], "ous.*Vale"),
    ([(ESSOS + ('ous',), [''])], 'ous'),
    ([(ESSOS + ('ous',), [1])], 'ous'),
    ([(G + ('scope',), 'local')], "scope.*global, universal, domainlocal"),
    ([(G + ('ou',), 'Nowhere')], "ou.*group Dothraki"),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F', 'surname': 'S', 'ou': 'Nowhere'})], "ou.*user u"),
    ([(G + ('members',), ['nope.local\\a'])], "nope.local"),
    ([(G + ('members',), 'a')], 'members'),
    ([(G + ('members',), ['north.sevenkingdoms.local\\a'])], 'group Dothraki'),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F', 'surname': 'S', 'groups': 'Dothraki'})], "groups.*user u"),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F', 'surname': 'S', 'groups': [1]})], "groups.*user u"),
    ([(ESSOS + ('users', 'u'), {'firstname': 'F', 'surname': 'S', 'sensitive': 'yes'})], "sensitive.*user u"),
    ([(SRV03 + ('laps',), 'yes')], "laps.*host srv03"),
    ([(SRV03 + ('ca',), 1)], "ca.*host srv03"),
    ([(('hosts', 'lnx'), dict(LINUX, laps=True))], "laps.*host lnx"),
    ([(('hosts', 'lnx'), dict(LINUX, ca=True))], "ca.*host lnx"),
    ([(('hosts', 'ws'), {'hostname': 'ws', 'os': 'win11', 'role': 'workstation', 'octet': 40, 'cpus': 1, 'memory': 1024, 'laps': True})], "laps.*host ws"),
    ([(('hosts', 'ws'), {'hostname': 'ws', 'os': 'win11', 'role': 'workstation', 'domain': 'essos.local', 'octet': 40, 'cpus': 1, 'memory': 1024, 'ca': True})], "ca.*host ws"),
    ([(('hosts', 'dc03', 'laps'), True)], "laps.*host dc03"),
    ([(SRV03 + ('local_groups',), {'Administrators': ['T1-ServerAdmins']})], "local_groups.*host srv03"),
    ([(SRV03 + ('local_groups',), {'Administrators': ['NOPE\\a']})], "local_groups.*NOPE"),
    ([(SRV03 + ('local_groups',), {'Administrators': 'ESSOS\\a'})], "local_groups.*host srv03"),
    ([(('hosts', 'lnx'), dict(LINUX, local_groups={'Administrators': ['ESSOS\\a']}))], "local_groups.*host lnx"),
    ([(ESSOS + ('parent',), 'sevenkingdoms.local')], "trust.*essos.local"),
    ([(ESSOS + ('trust',), 'north.sevenkingdoms.local')], "trust.*north.sevenkingdoms.local"),
    ([(('settings', 'all'), {'no.such': 'on'})], "no.such"),
    ([(('settings', 'all'), {'net.llmnr': 'maybe'})], "net.llmnr.*disabled, enabled"),
    ([(SRV02 + ('settings',), {'dc.maq': 11})], "dc.maq.*0, 1, 2"),
    ([(SRV02 + ('settings',), {'net.llmnr': 1.5})], "net.llmnr"),
    ([(('settings', 'dc'), {'adcs.editf_san': 'on'})], "host dc01: setting adcs.editf_san"),
    ([(('settings', 'server'), {'dc.spooler': 'enabled'})], "host srv02: setting dc.spooler applies to DCs only"),
])
def test_invalid_content_rejected(patches, message):
    with pytest.raises(GoadError, match=message):
        _lab(*patches)


def test_two_ca_hosts_in_one_domain_refused():
    with pytest.raises(GoadError, match=r'ca.*essos.local'):
        _lab((('hosts', 'srv04'), {'hostname': 'srv04', 'os': 'win2022', 'role': 'server', 'domain': 'essos.local',
                                   'octet': 24, 'cpus': 1, 'memory': 1024, 'ca': True}))



def test_unquoted_hex_cert_mapping_accepted():
    text = yaml.safe_dump(BASE).replace("dns_forwarder: 1.1.1.1", "dns_forwarder: 1.1.1.1\nsettings:\n  dc:\n    dc.cert_mapping: 0x4")
    assert yaml.safe_load(text)['settings']['dc']['dc.cert_mapping'] == 4
    lab = parse_lab(text, 'lab.yml')
    assert lab.effective_settings('dc01')['dc.cert_mapping'] == '0x4'


SEVEN = ('domains', 'sevenkingdoms.local')
TYWIN = {'firstname': 'Tywin', 'surname': 'Lannister'}


@pytest.mark.parametrize('patches, message', [
    ([(ESSOS + ('users',), {'viserys': {**TYWIN, 'groups': ['Dothrak']}})],
     r"user viserys in domain essos.local names unknown group 'Dothrak'"),
    ([(ESSOS + ('groups', 'Dothraki', 'managed_by'), 'khal.drogo')],
     r"group Dothraki in domain essos.local has unknown managed_by 'khal.drogo'"),
    ([(ESSOS + ('groups', 'Dothraki', 'members'), ['khal.drogo'])],
     r"unknown member 'khal.drogo' of group Dothraki in domain essos.local: not a user or group of essos.local"),
    ([(ESSOS + ('groups', 'Dothraki', 'scope'), 'domainlocal'),
      (ESSOS + ('groups', 'Dothraki', 'members'), ['sevenkingdoms.local\\'])],
     r"member 'sevenkingdoms.local\\\\' of group Dothraki in domain essos.local has an empty name"),
    ([(ESSOS + ('groups', 'Dothraki', 'scope'), 'domainlocal'),
      (ESSOS + ('groups', 'Dothraki', 'members'), ['sevenkingdoms.local\\tywin.lanister']),
      (SEVEN + ('users',), {'tywin.lannister': TYWIN})],
     r"unknown member 'sevenkingdoms.local\\\\tywin.lanister' of group Dothraki in domain essos.local: not a user or group of sevenkingdoms.local"),
    ([(ESSOS + ('groups', 'Dothraki', 'scope'), 'domainlocal'),
      (ESSOS + ('groups', 'Dothraki', 'members'), ['westeros.local\\tywin.lannister'])],
     r"unknown domain 'westeros.local'"),
])
def test_content_references_checked(patches, message):
    with pytest.raises(GoadError, match=message):
        _lab(*patches)


def test_content_references_resolve():
    lab = _lab((ESSOS + ('users',), {'viserys': {**TYWIN, 'groups': ['Dothraki', 'Domain Admins', 'Protected Users']}}),
               (ESSOS + ('groups', 'Dothraki', 'scope'), 'domainlocal'),
               (ESSOS + ('groups', 'Dothraki', 'managed_by'), 'Administrator'),
               (ESSOS + ('groups', 'Dothraki', 'members'), ['viserys', 'sevenkingdoms.local\\tywin.lannister', 'sevenkingdoms.local\\Domain Admins']),
               (SEVEN + ('users',), {'tywin.lannister': TYWIN}))
    assert lab.domains['essos.local'].groups['Dothraki'].managed_by == 'Administrator'


def test_parse_lab_records_scenarios(monkeypatch):
    frag = {'domains': {'{domain}': {'users': {'new.user': {'firstname': 'A', 'surname': 'B'}}}}}
    cat = {'t': scenarios.Scenario('t', '', 'domain', frag)}
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: cat)
    text = shipped_lab('2domains').read_text() + 'scenarios:\n  - {name: t, target: dc02}\n'
    lab = parse_lab(text, 'x')
    assert lab.scenarios == (ScenarioRef('t', 'dc02'),)
    assert 'new.user' in lab.domains['north.sevenkingdoms.local'].users


def test_shipped_labs_have_no_scenarios():
    for name in LAB_NAMES:
        assert load_lab(shipped_lab(name)).scenarios == ()


SVC = {'firstname': 'S', 'surname': 'V'}


def test_user_and_host_primitives_parse():
    from goad.lab.definition import DelegationDef
    lab = _lab((ESSOS + ('users',), {
        'svc.kerb': {**SVC, 'password': 'Bb1!', 'spns': ['MSSQLSvc/svc-kerb.essos.local:1433']},
        'asrep': {**SVC, 'preauth': False},
        'svc.any': {**SVC, 'delegation': {'constrained': ['CIFS/meereen.essos.local', 'CIFS/meereen'],
                                          'protocol_transition': True}},
        'svc.unc': {**SVC, 'delegation': {'unconstrained': True}}}),
        (ESSOS + ('groups', 'Dothraki', 'groups'), ['Administrators', 'Khals']),
        (ESSOS + ('groups', 'Khals'), {'scope': 'global'}),
        (SRV03 + ('delegation',), {'constrained': ['HTTP/meereen.essos.local']}))
    users = lab.domains['essos.local'].users
    assert users['svc.kerb'].password == 'Bb1!' and users['svc.kerb'].spns == ('MSSQLSvc/svc-kerb.essos.local:1433',)
    assert users['svc.kerb'].preauth is True and users['svc.kerb'].delegation is None
    assert users['asrep'].preauth is False and users['asrep'].password is None and users['asrep'].spns == ()
    assert users['svc.any'].delegation == DelegationDef(constrained=('CIFS/meereen.essos.local', 'CIFS/meereen'),
                                                        protocol_transition=True)
    assert users['svc.unc'].delegation == DelegationDef(unconstrained=True)
    assert lab.domains['essos.local'].groups['Dothraki'].groups == ('Administrators', 'Khals')
    assert lab.domains['essos.local'].groups['Khals'].groups == ()
    assert lab.hosts['srv03'].delegation == DelegationDef(constrained=('HTTP/meereen.essos.local',))
    assert lab.hosts['srv02'].delegation is None


def test_delegation_unconstrained_with_constrained():
    lab = _lab((SRV03 + ('delegation',), {'unconstrained': True, 'constrained': ['HTTP/x'], 'protocol_transition': True}),
               (ESSOS + ('users', 'u'), {**SVC, 'delegation': {'unconstrained': True, 'constrained': ['CIFS/x']}}))
    d = lab.hosts['srv03'].delegation
    assert d.unconstrained and d.constrained == ('HTTP/x',) and d.protocol_transition
    u = lab.domains['essos.local'].users['u'].delegation
    assert u.unconstrained and u.constrained == ('CIFS/x',)


U = ESSOS + ('users', 'u')


@pytest.mark.parametrize('patches, message', [
    ([(U, {**SVC, 'delegation': {}})], r"delegation.*user u.*at least one of"),
    ([(U, {**SVC, 'delegation': {'unconstrained': False}})], r"delegation.*user u.*at least one of"),
    ([(U, {**SVC, 'delegation': {'unconstrained': True, 'protocol_transition': True}})],
     r"protocol_transition.*user u.*only with constrained"),
    ([(U, {**SVC, 'delegation': {'constrained': []}})], r"constrained.*user u"),
    ([(U, {**SVC, 'delegation': {'constrained': 'CIFS/x'}})], r"constrained.*user u"),
    ([(U, {**SVC, 'delegation': {'constrained': ['CIFS/x'], 'protocol_transition': 'yes'}})],
     r"protocol_transition.*user u"),
    ([(U, {**SVC, 'delegation': {'constrained': ['CIFS/x'], 'colour': 1}})], r"unknown key 'colour'.*user u"),
    ([(U, {**SVC, 'delegation': 'unconstrained'})], r"delegation.*user u.*mapping"),
    ([(U, {**SVC, 'password': ''})], r"password.*user u"),
    ([(U, {**SVC, 'spns': 'HTTP/x'})], r"spns.*user u"),
    ([(U, {**SVC, 'preauth': 'no'})], r"preauth.*user u"),
    ([(('hosts', 'dc03', 'delegation'), {'unconstrained': True})], r"delegation.*host dc03"),
    ([(('hosts', 'ws'), {'hostname': 'ws', 'os': 'win11', 'role': 'workstation', 'octet': 40, 'cpus': 1,
                         'memory': 1024, 'delegation': {'unconstrained': True}})], r"delegation.*host ws"),
    ([(SRV03 + ('delegation',), {'unconstrained': True, 'protocol_transition': False})],
     r"protocol_transition.*host srv03"),
    ([(G + ('groups',), ['Khals'])], r"group Dothraki in domain essos.local names unknown group 'Khals'"),
    ([(G + ('groups',), ['Dothraki'])], r"group Dothraki in domain essos.local.*itself"),
    ([(G + ('groups',), 'Administrators')], r"groups.*group Dothraki"),
])
def test_primitives_rejected(patches, message):
    with pytest.raises(GoadError, match=message):
        _lab(*patches)


ACL_USERS = {'attacker': SVC, 'victim': SVC}


def _acl_lab(*acls, gpos=None, extra=()):
    patches = [(ESSOS + ('users',), dict(ACL_USERS)), (ESSOS + ('ous',), ['Vale']), (ESSOS + ('acls',), list(acls)),
               (SEVEN + ('users',), {'tywin.lannister': TYWIN})]
    if gpos is not None:
        patches.append((ESSOS + ('gpos',), gpos))
    return _lab(*patches, *extra)


def test_acl_and_gpo_primitives_parse():
    from goad.lab.definition import AclDef, GpoDef
    lab = _acl_lab(
        {'principal': 'attacker', 'right': 'GenericAll', 'object': 'user:victim'},
        {'principal': 'attacker', 'right': 'AddMember', 'object': 'group:Dothraki'},
        {'principal': 'attacker', 'right': 'WriteDacl', 'object': 'ou:Vale', 'inherit': 'all'},
        {'principal': 'attacker', 'right': 'GenericWrite', 'object': 'gpo:scn-gpo'},
        {'principal': 'attacker', 'right': 'GenericAll', 'object': 'computer:srv03'},
        {'principal': 'attacker', 'right': 'GenericAll', 'object': 'adminsdholder'},
        {'principal': 'NT AUTHORITY\\ANONYMOUS LOGON', 'right': 'ReadAll', 'object': 'domain', 'inherit': 'all'},
        {'principal': 'Everyone', 'right': 'ReadAll', 'object': 'domain'},
        {'principal': 'sevenkingdoms.local\\tywin.lannister', 'right': 'ForceChangePassword', 'object': 'user:victim'},
        {'principal': 'Domain Users', 'right': 'WriteSPN', 'object': 'user:Administrator'},
        {'principal': 'attacker', 'right': 'GenericAll', 'object': 'template:ESC4'},
        gpos={'scn-gpo': {}, 'vale-gpo': {'link': 'ou:Vale'}},
        extra=[(SRV03 + ('cert_templates',), {'ESC4': {'json': 'ESC4.json'}})])
    d = lab.domains['essos.local']
    assert d.acls[0] == AclDef(principal='attacker', right='GenericAll', object='user:victim', inherit='none')
    assert d.acls[2].inherit == 'all' and len(d.acls) == 11
    assert d.gpos == {'scn-gpo': GpoDef(name='scn-gpo', link='domain'), 'vale-gpo': GpoDef(name='vale-gpo', link='ou:Vale')}
    assert lab.domains['sevenkingdoms.local'].acls == () and lab.domains['sevenkingdoms.local'].gpos == {}


def _ace(**kw):
    return {'principal': 'attacker', 'right': 'GenericAll', 'object': 'user:victim', **kw}


@pytest.mark.parametrize('acls, gpos, message', [
    ([_ace(right='FullControl')], None, r"unknown right 'FullControl'.*domain essos.local"),
    ([_ace(object='printer:x')], None, r"unknown object kind 'printer'.*domain essos.local"),
    ([_ace(object='user:')], None, r"object 'user:'.*domain essos.local"),
    ([_ace(object='domain:x')], None, r"object 'domain:x'.*domain essos.local"),
    ([_ace(object='user:nobody')], None, r"unknown user 'nobody'.*domain essos.local"),
    ([_ace(object='group:nobody')], None, r"unknown group 'nobody'.*domain essos.local"),
    ([_ace(object='computer:srv02')], None, r"computer 'srv02'.*not a host of essos.local"),
    ([_ace(object='computer:nope')], None, r"computer 'nope'.*not a host of essos.local"),
    ([_ace(object='ou:Nowhere')], None, r"unknown ou 'Nowhere'.*domain essos.local"),
    ([_ace(object='gpo:nope')], None, r"unknown gpo 'nope'.*domain essos.local"),
    ([_ace(object='gpo:g', right='WriteDacl')], {'g': {}}, r"gpo.*only GenericAll or GenericWrite"),
    ([_ace(inherit='descendents')], None, r"inherit 'descendents'.*none or all"),
    ([_ace(principal='nobody')], None, r"unknown principal 'nobody'.*domain essos.local"),
    ([_ace(principal='westeros.local\\x')], None, r"unknown principal 'westeros.local\\\\x'"),
    ([_ace(principal='sevenkingdoms.local\\nobody')], None, r"unknown principal 'sevenkingdoms.local\\\\nobody'"),
    ([_ace(principal='NT AUTHORITY\\SYSTEM')], None, r"unknown principal 'NT AUTHORITY\\\\SYSTEM'"),
    ([_ace(object='gpo:g', principal='Everyone')], {'g': {}}, r"principal 'Everyone' on gpo.*must be a user or group of essos.local"),
    ([_ace(object='gpo:g', inherit='all')], {'g': {}}, r"inherit 'all' on gpo.*only none"),
    ([_ace(object='template:ESC1')], None, r"template 'ESC1'.*not in cert_templates of the CA host of essos.local"),
    ([_ace(colour=1)], None, r"unknown key 'colour'.*acl"),
    ([{'principal': 'attacker', 'right': 'GenericAll'}], None, r"missing key 'object'.*acl"),
    ('nope', None, r"acls.*domain essos.local.*list"),
    ([], {'g': {'link': 'ou:Nowhere'}}, r"unknown ou 'Nowhere' in link of gpo g in domain essos.local: not in ous of essos.local"),
    ([], {'g': {'link': 'site'}}, r"invalid link 'site' in gpo g.*domain or ou:<name>"),
    ([], {'g': {'colour': 1}}, r"unknown key 'colour'.*gpo g"),
    ([], ['g'], r"gpos.*domain essos.local.*mapping"),
])
def test_acl_and_gpo_rejected(acls, gpos, message):
    with pytest.raises(GoadError, match=message):
        if acls == 'nope':
            _lab((ESSOS + ('acls',), 'nope'))
        else:
            _acl_lab(*acls, gpos=gpos)


def _adcs_lab(templates=None, ca_acl=None, host=SRV03, extra=()):
    patches = [(ESSOS + ('users',), dict(ACL_USERS)), (ESSOS + ('groups', 'scn-esc13-group'), {'scope': 'universal'})]
    if templates is not None:
        patches.append((host + ('cert_templates',), templates))
    if ca_acl is not None:
        patches.append((host + ('ca_acl',), ca_acl))
    return _lab(*patches, *extra)


def test_adcs_primitives_parse():
    from goad.lab.definition import CertTemplateDef
    lab = _adcs_lab(
        {'ESC1': {'json': 'ESC1.json'},
         'ESC13': {'json': 'ESC13.json', 'enroll': ['attacker'], 'issuance_policy': {'group': 'scn-esc13-group'}},
         'WebServer': {'builtin': True, 'enroll': ['Domain Users', 'sevenkingdoms.local\\Domain Users']}},
        [{'principal': 'attacker', 'right': 'ManageCA'}, {'principal': 'victim', 'right': 'ManageCertificates'}])
    h = lab.hosts['srv03']
    assert h.cert_templates == {
        'ESC1': CertTemplateDef(name='ESC1', json='ESC1.json'),
        'ESC13': CertTemplateDef(name='ESC13', json='ESC13.json', enroll=('attacker',), issuance_group='scn-esc13-group'),
        'WebServer': CertTemplateDef(name='WebServer', builtin=True,
                                     enroll=('Domain Users', 'sevenkingdoms.local\\Domain Users'))}
    assert h.cert_templates['ESC1'].enroll == ('Domain Users',) and h.cert_templates['ESC1'].builtin is False
    assert h.ca_acl == (('attacker', 'ManageCA'), ('victim', 'ManageCertificates'))
    assert lab.hosts['srv02'].cert_templates == {} and lab.hosts['srv02'].ca_acl == ()


def test_template_acl_names_ca_template():
    lab = _acl_lab({'principal': 'attacker', 'right': 'GenericAll', 'object': 'template:ESC4'},
                   extra=[(SRV03 + ('cert_templates',), {'ESC4': {'json': 'ESC4.json'}})])
    assert lab.domains['essos.local'].acls[0].target == 'ESC4'


@pytest.mark.parametrize('templates, ca_acl, host, message', [
    ({'ESC1': {'json': 'ESC1.json'}}, None, SRV02, r"cert_templates.*host srv02.*ca: true"),
    (None, [{'principal': 'Domain Users', 'right': 'ManageCA'}], SRV02, r"ca_acl.*host srv02.*ca: true"),
    ({'ESC1': {}}, None, SRV03, r"template ESC1.*exactly one of json and builtin"),
    ({'ESC1': {'json': 'ESC1.json', 'builtin': True}}, None, SRV03, r"template ESC1.*exactly one of json and builtin"),
    ({'ESC1': {'builtin': False}}, None, SRV03, r"template ESC1.*exactly one of json and builtin"),
    ({'ESC1': {'json': 'ESC99.json'}}, None, SRV03, r"json 'ESC99.json'.*template ESC1.*ansible/roles/adcs/files"),
    ({'ESC1': {'json': '../ad_acls/files/ace.ps1'}}, None, SRV03, r"json '../ad_acls/files/ace.ps1'.*template ESC1"),
    ({'ESC1': {'json': 'ESC1.json', 'colour': 1}}, None, SRV03, r"unknown key 'colour'.*template ESC1"),
    ({'ESC1': {'json': 'ESC1.json', 'enroll': 'Domain Users'}}, None, SRV03, r"enroll.*template ESC1"),
    ({'ESC1': {'json': 'ESC1.json', 'enroll': ['nobody']}}, None, SRV03, r"unknown principal 'nobody'.*template ESC1"),
    ({'ESC 1': {'json': 'ESC1.json'}}, None, SRV03, r"template 'ESC 1'.*spaces"),
    ({'ESC13': {'json': 'ESC13.json', 'issuance_policy': {'group': 'nogroup'}}}, None, SRV03,
     r"issuance group 'nogroup'.*template ESC13 in host srv03.*not a universal group defined in groups of essos.local"),
    ({'ESC13': {'json': 'ESC13.json', 'issuance_policy': {'group': 'Dothraki'}}}, None, SRV03,
     r"issuance group 'Dothraki'.*template ESC13 in host srv03.*not a universal group"),
    ({'ESC13': {'json': 'ESC13.json', 'issuance_policy': {'group': 'Domain Admins'}}}, None, SRV03,
     r"issuance group 'Domain Admins'.*template ESC13 in host srv03.*not a universal group"),
    ({'ESC13': {'json': 'ESC13.json', 'issuance_policy': {'colour': 1}}}, None, SRV03, r"unknown key 'colour'.*issuance_policy"),
    ({'ESC13': {'json': 'ESC13.json', 'issuance_policy': {}}}, None, SRV03, r"missing key 'group'.*issuance_policy"),
    ('ESC1', None, SRV03, r"cert_templates.*host srv03.*mapping"),
    (None, [{'principal': 'attacker', 'right': 'Owner'}], SRV03, r"unknown right 'Owner'.*ca_acl.*host srv03.*ManageCA, ManageCertificates"),
    (None, [{'principal': 'nobody', 'right': 'ManageCA'}], SRV03, r"unknown principal 'nobody'.*ca_acl.*host srv03"),
    (None, [{'principal': 'attacker'}], SRV03, r"missing key 'right'.*ca_acl"),
    (None, [['attacker', 'ManageCA']], SRV03, r"ca_acl.*host srv03.*mapping"),
    (None, {'principal': 'attacker', 'right': 'ManageCA'}, SRV03, r"ca_acl.*host srv03.*list"),
])
def test_adcs_primitives_rejected(templates, ca_acl, host, message):
    with pytest.raises(GoadError, match=message):
        _adcs_lab(templates, ca_acl, host)
