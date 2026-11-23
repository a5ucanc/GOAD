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
