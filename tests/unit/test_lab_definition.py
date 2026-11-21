import copy

import pytest
import yaml

from goad import GoadError
from goad.lab.definition import LAB_NAMES, load_lab, parse_lab, shipped_lab


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
