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


def test_local_admin():
    lab, target = _enabled('local-admin')
    assert 'NORTH\\scn-local-admin' in lab.hosts[target].local_groups['Administrators']
    assert _user(lab, 'north.sevenkingdoms.local', 'scn-local-admin').password == 'Aa1234567890!'
