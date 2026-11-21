"""The shipped lab.yml files carry the AD content of labs/<lab>/reference/config.json."""
import json

import pytest

from goad.lab.definition import LAB_NAMES, REPO, load_lab, shipped_lab
from goad.lab.settings_catalog import normalize_value

ASR_LSASS = 'block lsass stealing'


def _ou(path):
    first = path.split(',')[0]
    return first[3:] if first.startswith('OU=') else None


def lab_view(lab):
    domains = {}
    for fqdn, d in lab.domains.items():
        domains[fqdn] = {
            'ous': set(d.ous),
            'groups': {n: (g.scope, g.ou, g.managed_by, sorted(g.members)) for n, g in d.groups.items()},
            'users': {n: (u.firstname, u.surname, u.city, u.description, sorted(u.groups), u.ou, u.sensitive)
                      for n, u in d.users.items()}}
    hosts = {n: (h.laps, h.ca, {g: sorted(m) for g, m in h.local_groups.items()}, lab.effective_settings(n))
             for n, h in lab.hosts.items()}
    return {'domains': domains, 'hosts': hosts}


def _member(domains, own, member):
    """Reference member to lab.yml form; None when the member's domain is not in the lab."""
    prefix, _, name = member.partition('\\')
    for fqdn, d in domains.items():
        if prefix.lower() in (fqdn.lower(), d['netbios_name'].lower()):
            return name if fqdn == own else f'{fqdn}\\{name}'
    return None


def _netbios_member(netbios, member):
    """Local group member: the reference writes the NETBIOS prefix in lowercase, lab.yml in uppercase."""
    prefix, _, name = member.partition('\\')
    return f'{netbios[prefix.lower()]}\\{name}'


def reference_view(config, lab_name):
    ref_domains = config['domains']
    domains = {}
    sensitive = set()
    for h in config['hosts'].values():
        for entry in h.get('security_vars', {}).get('account_is_sensitive', {}).values():
            sensitive.add((h['domain'], entry['account']))
    for fqdn, d in ref_domains.items():
        extra = d.get('multi_domain_groups_member', {})
        groups = {}
        for scope, by_name in d['groups'].items():
            for name, g in by_name.items():
                found = [_member(ref_domains, fqdn, m) for m in g.get('members', []) + extra.get(name, [])]
                groups[name] = (scope, _ou(g['path']), g.get('managed_by'), sorted(m for m in found if m))
        users = {n: (u['firstname'], u['surname'], u.get('city'), u.get('description'), sorted(u.get('groups', [])),
                     _ou(u['path']) if 'path' in u else None, (fqdn, n) in sensitive)
                 for n, u in d['users'].items()}
        domains[fqdn] = {'ous': set(d['organisation_units']), 'groups': groups, 'users': users}
    hosts = {}
    for name, h in config['hosts'].items():
        settings = {k: normalize_value(v, k) for k, v in config['base_settings'][name].items()}
        assert 'enable_run_as_ppl' in h['security']
        settings['lsa.ppl'] = 'on'
        if ASR_LSASS in h.get('security_vars', {}).get('asr', {}):
            settings['defender.asr_lsass'] = 'block'
        local_groups = dict(h['local_groups'])
        if 'Remote Desktop Users' in h:
            local_groups['Remote Desktop Users'] = h['Remote Desktop Users']
        netbios = {d['netbios_name'].lower(): d['netbios_name'] for d in ref_domains.values()}
        hosts[name] = (bool(h.get('use_laps')), name in config['capabilities'].get('adcs', []),
                       {g: sorted(_netbios_member(netbios, m) for m in ms) for g, ms in local_groups.items()}, settings)
    return {'domains': domains, 'hosts': hosts}


@pytest.mark.parametrize('name', LAB_NAMES)
def test_lab_yml_matches_reference(name):
    config = json.loads((REPO / 'labs' / name / 'reference' / 'config.json').read_text())['lab']
    assert lab_view(load_lab(shipped_lab(name))) == reference_view(config, name)


def test_spot_values():
    lab = load_lab(shipped_lab('2forests'))
    essos = lab.domains['essos.local']
    assert essos.groups['DragonsFriends'].members == ('sevenkingdoms.local\\tyron.lannister', 'daenerys.targaryen')
    assert essos.users['daenerys.targaryen'].sensitive is True
    assert lab.hosts['srv03'].laps and lab.hosts['srv03'].ca and lab.hosts['dc01'].ca
    assert lab.hosts['srv03'].local_groups['Remote Desktop Users'] == ('ESSOS\\Dothraki',)
    assert lab.effective_settings('dc02')['ldap.channel_binding'] == 'always'
    assert 'trust.sid_history' not in lab.effective_settings('dc02')
    assert 'AcrossTheNarrowSea' in load_lab(shipped_lab('1domain')).domains['sevenkingdoms.local'].groups
