import pytest
import yaml

from goad.lab.definition import LAB_NAMES, load_lab, parse_lab, shipped_lab
from goad.lab.scenarios import load_catalogue, valid_targets

NAMES = {
    'smb-signing-off', 'llmnr', 'mdns', 'smbv1', 'webdav', 'credssp', 'defender-off', 'firewall-off',
    'rc4', 'maq', 'printerbug', 'ntlm-downgrade', 'ldap-signing-off', 'ldap-cbt-off', 'sid-history',
    'esc6', 'esc8', 'esc10-case1', 'esc10-case2', 'esc11',
    'kerberoast', 'asrep-roast', 'unconstrained-user', 'constrained-deleg-any', 'unconstrained-computer',
    'constrained-deleg-kerb', 'local-admin',
    'acl-addmember', 'acl-adminsdholder', 'acl-forcechangepassword', 'acl-genericall-computer',
    'acl-genericall-group', 'acl-genericall-user', 'acl-genericwrite-user', 'acl-self-membership',
    'acl-writedacl-ou', 'acl-writedacl-user', 'acl-writeowner', 'acl-writeproperty', 'anonymous-rpc',
    'writespn', 'rbcd', 'foreign-group-acl', 'gpo-abuse',
    'esc1', 'esc2', 'esc3', 'esc4', 'esc7', 'esc9', 'esc13', 'esc15',
}

# name -> (target kind, [(setting key, vulnerable value)]); values as effective_settings reports them
SETTING_CASES = [
    ('smb-signing-off', [('smb.signing', 'optional')]),
    ('llmnr', [('net.llmnr', 'enabled'), ('net.nbtns', 'enabled')]),
    ('mdns', [('net.mdns', 'enabled')]),
    ('smbv1', [('smb.v1', 'enabled')]),
    ('webdav', [('net.webclient', 'present')]),
    ('credssp', [('winrm.credssp', 'server')]),
    ('defender-off', [('defender.realtime', 'off')]),
    ('firewall-off', [('firewall.state', 'off')]),
    ('rc4', [('kerberos.rc4', 'enabled')]),
    ('maq', [('dc.maq', 10)]),
    ('printerbug', [('dc.spooler', 'enabled')]),
    ('ntlm-downgrade', [('ntlm.lmcompat', 2)]),
    ('ldap-signing-off', [('ldap.signing', 'none')]),
    ('ldap-cbt-off', [('ldap.channel_binding', 'never')]),
    ('sid-history', [('trust.sid_history', 'enabled')]),
    ('esc6', [('adcs.editf_san', 'on')]),
    ('esc8', [('adcs.web_enrollment', 'on')]),
    ('esc10-case1', [('dc.strong_cert_binding', 0)]),
    ('esc10-case2', [('dc.cert_mapping', '0x4')]),
    ('esc11', [('adcs.enforce_encrypt', 'off')]),
]


def _text(lab):
    return shipped_lab(lab).read_text()


def _with(text, name, target):
    return text.rstrip('\n') + f'\nscenarios:\n- {{name: {name}, target: {target}}}\n'


def test_catalogue_names():
    assert set(load_catalogue()) == NAMES


def test_every_scenario_expands_everywhere():
    catalogue = load_catalogue()
    for lab in LAB_NAMES:
        text = _text(lab)
        raw = yaml.safe_load(text)
        for name, sc in catalogue.items():
            for target in valid_targets(raw, sc.kind):
                parse_lab(_with(text, name, target), f'{lab}+{name}@{target}')


def test_descriptions_present():
    assert all(s.description for s in load_catalogue().values())


@pytest.mark.parametrize('name,pairs', SETTING_CASES)
def test_setting_scenarios_change_effective_settings(name, pairs):
    text = _text('2forests')
    raw = yaml.safe_load(text)
    sc = load_catalogue()[name]
    target = valid_targets(raw, sc.kind)[0]
    base = parse_lab(text, '2forests')
    lab = parse_lab(_with(text, name, target), '2forests')
    for key, value in pairs:
        want = str(value)
        assert lab.effective_settings(target)[key] == want
        assert base.effective_settings(target).get(key) != want


def _enabled(name):
    text = _text('2forests')
    raw = yaml.safe_load(text)
    target = valid_targets(raw, load_catalogue()[name].kind)[0]
    return parse_lab(_with(text, name, target), '2forests'), target


def _user(lab, domain, user):
    return next(u for u in lab.domains[domain].users if u.name == user) if isinstance(
        lab.domains[domain].users, (list, tuple)) else lab.domains[domain].users[user]


def test_kerberoast_spn():
    lab, _ = _enabled('kerberoast')
    assert _user(lab, 'sevenkingdoms.local', 'svc_kerb').spns == ('MSSQLSvc/svc-kerb.sevenkingdoms.local:1433',)


def test_asrep_roast_preauth_off():
    lab, _ = _enabled('asrep-roast')
    assert _user(lab, 'sevenkingdoms.local', 'asrep_user').preauth is False


def test_unconstrained_user():
    lab, _ = _enabled('unconstrained-user')
    u = _user(lab, 'sevenkingdoms.local', 'scn-unconst-svc')
    assert u.spns == ('HTTP/scn-unconst.sevenkingdoms.local',) and u.delegation.unconstrained


def test_constrained_deleg_any():
    lab, _ = _enabled('constrained-deleg-any')
    u = _user(lab, 'sevenkingdoms.local', 'scn-cdany-svc')
    assert u.spns == ('HTTP/scn-cdany.sevenkingdoms.local',)
    assert u.delegation.constrained == ('CIFS/kingslanding.sevenkingdoms.local', 'CIFS/kingslanding')
    assert u.delegation.protocol_transition and not u.delegation.unconstrained


def test_unconstrained_computer():
    lab, target = _enabled('unconstrained-computer')
    assert lab.hosts[target].delegation.unconstrained


def test_constrained_deleg_kerb():
    lab, target = _enabled('constrained-deleg-kerb')
    d = lab.hosts[target].delegation
    assert d.constrained == ('HTTP/winterfell.north.sevenkingdoms.local', 'HTTP/winterfell')
    assert not d.protocol_transition and not d.unconstrained


def test_unconstrained_and_constrained_deleg_on_one_server():
    text = _text('2domains')
    text = text.rstrip('\n') + ('\nscenarios:\n- {name: unconstrained-computer, target: srv02}\n'
                               '- {name: constrained-deleg-kerb, target: srv02}\n')
    d = parse_lab(text, '2domains').hosts['srv02'].delegation
    assert d.unconstrained and d.constrained and not d.protocol_transition


def test_local_admin():
    lab, target = _enabled('local-admin')
    assert 'NORTH\\scn-local-admin' in lab.hosts[target].local_groups['Administrators']
    assert _user(lab, 'north.sevenkingdoms.local', 'scn-local-admin').password == 'Aa1234567890!'


def _acls(lab, domain):
    return {(a.principal, a.right, a.object, a.inherit) for a in lab.domains[domain].acls}


ACL_CASES = [
    ('acl-addmember', 'scn-acl-add-attacker', 'AddMember', 'group:scn-acl-add-group', 'all'),
    ('acl-adminsdholder', 'scn-acl-sdh-attacker', 'GenericAll', 'adminsdholder', 'none'),
    ('acl-forcechangepassword', 'scn-acl-fcp-attacker', 'ForceChangePassword', 'user:scn-acl-fcp-victim', 'none'),
    ('acl-genericall-computer', 'scn-acl-gac-attacker', 'GenericAll', 'computer:dc01', 'none'),
    ('acl-genericall-user', 'scn-acl-gau-attacker', 'GenericAll', 'user:scn-acl-gau-victim', 'none'),
    ('acl-genericwrite-user', 'scn-acl-gwu-attacker', 'GenericWrite', 'user:scn-acl-gwu-victim', 'none'),
    ('acl-self-membership', 'scn-acl-sm-attacker', 'SelfMembership', 'group:scn-acl-sm-group', 'none'),
    ('acl-writedacl-ou', 'scn-acl-wdo-attacker', 'WriteDacl', 'ou:scn-acl-wdo', 'none'),
    ('acl-writedacl-user', 'scn-acl-wdu-attacker', 'WriteDacl', 'user:scn-acl-wdu-victim', 'none'),
    ('acl-writeowner', 'scn-acl-wo-attacker', 'WriteOwner', 'group:scn-acl-wo-group', 'none'),
    ('acl-writeproperty', 'scn-acl-wp-attacker', 'WriteProperty', 'user:scn-acl-wp-victim', 'all'),
    ('writespn', 'scn-wspn-attacker', 'WriteSPN', 'user:scn-wspn-victim', 'none'),
    ('anonymous-rpc', 'NT AUTHORITY\\ANONYMOUS LOGON', 'ReadAll', 'domain', 'all'),
    ('gpo-abuse', 'scn-gpo-attacker', 'GenericWrite', 'gpo:scn-gpo-abuse', 'none'),
]


@pytest.mark.parametrize('name,principal,right,obj,inherit', ACL_CASES)
def test_acl_scenarios_grant_ace_in_target_domain(name, principal, right, obj, inherit):
    lab, target = _enabled(name)
    domain = lab.hosts[target].domain
    assert (principal, right, obj, inherit) in _acls(lab, domain)
    base = parse_lab(_text('2forests'), '2forests')
    assert all(_acls(lab, d) == _acls(base, d) for d in lab.domains if d != domain)


def test_acl_writedacl_ou():
    lab, _ = _enabled('acl-writedacl-ou')
    d = lab.domains['sevenkingdoms.local']
    assert 'scn-acl-wdo' in d.ous and d.users['scn-acl-wdo-victim'].ou == 'scn-acl-wdo'


def test_acl_genericall_group():
    lab, target = _enabled('acl-genericall-group')
    domain = lab.hosts[target].domain
    assert lab.domains[domain].groups['scn-acl-gag-group'].scope == 'domainlocal'
    assert any(m.endswith('\\scn-acl-gag-group') for m in lab.hosts[target].local_groups['Administrators'])
    assert ('scn-acl-gag-attacker', 'GenericAll', 'group:scn-acl-gag-group', 'none') in _acls(lab, domain)


def test_rbcd():
    lab, target = _enabled('rbcd')
    domain = lab.hosts[target].domain
    assert ('scn-rbcd-attacker', 'GenericWrite', f'computer:{target}', 'none') in _acls(lab, domain)
    assert lab.effective_settings(lab.domains[domain].dc)['dc.maq'] == '10'


def test_foreign_group_acl():
    lab, target = _enabled('foreign-group-acl')
    domain = lab.hosts[target].domain
    other = next(d for d in lab.domains if d != domain and lab.forest_root(d) != lab.forest_root(domain))
    g = lab.domains[domain].groups['scn-foreign-group']
    assert g.scope == 'domainlocal' and g.members == (f'{other}\\scn-foreign-user',)
    assert 'scn-foreign-user' in lab.domains[other].users
    assert ('scn-foreign-group', 'GenericAll', f'computer:{target}', 'none') in _acls(lab, domain)


def test_gpo_abuse_defines_gpo():
    lab, _ = _enabled('gpo-abuse')
    assert lab.domains['sevenkingdoms.local'].gpos['scn-gpo-abuse'].link == 'domain'


def test_adcs_templates_land_on_ca():
    for name, templates in [('esc1', {'ESC1': 'ESC1.json'}), ('esc2', {'ESC2': 'ESC2.json'}),
                            ('esc3', {'ESC3-CRA': 'ESC3-CRA.json', 'ESC3': 'ESC3.json'}),
                            ('esc4', {'ESC4': 'ESC4.json'}), ('esc9', {'ESC9': 'ESC9.json'}),
                            ('esc13', {'ESC13': 'ESC13.json'})]:
        lab, target = _enabled(name)
        got = lab.hosts[target].cert_templates
        assert templates.items() <= {n: t.json for n, t in got.items()}.items(), name
        assert all(got[n].enroll == ('Domain Users',) for n in templates), name


def test_esc4_acl_on_template():
    lab, target = _enabled('esc4')
    assert ('scn-esc4-user', 'GenericAll', 'template:ESC4', 'none') in _acls(lab, lab.hosts[target].domain)


def test_esc7_ca_acl():
    lab, target = _enabled('esc7')
    assert ('scn-esc7-user', 'ManageCA') in lab.hosts[target].ca_acl
    assert 'scn-esc7-user' in lab.domains[lab.hosts[target].domain].users


def test_esc9_acl_and_binding():
    lab, target = _enabled('esc9')
    domain = lab.hosts[target].domain
    assert ('scn-esc9-attacker', 'GenericWrite', 'user:scn-esc9-victim', 'none') in _acls(lab, domain)
    assert lab.effective_settings(lab.domains[domain].dc)['dc.strong_cert_binding'] == '0'


def test_esc13_issuance_group():
    lab, target = _enabled('esc13')
    domain = lab.hosts[target].domain
    assert lab.hosts[target].cert_templates['ESC13'].issuance_group == 'scn-esc13-group'
    assert lab.domains[domain].groups['scn-esc13-group'].scope == 'universal'


def test_esc15_builtin_webserver():
    lab, target = _enabled('esc15')
    t = lab.hosts[target].cert_templates['WebServer']
    assert t.builtin and t.json is None and t.enroll == ('Domain Users',)


def test_substitute_merges_colliding_keys():
    from goad.lab.scenarios import substitute
    out = substitute({'hosts': {'{target}': {'a': {'x': 1}}, '{dc}': {'a': {'y': 2}, 'b': 3}}},
                     {'{target}': 'dc01', '{dc}': 'dc01'})
    assert out == {'hosts': {'dc01': {'a': {'x': 1, 'y': 2}, 'b': 3}}}
