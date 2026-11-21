import pytest

from goad.lab.settings_catalog import GROUP_SCOPES, SETTING_LAYERS, SETTINGS, normalize_value


def test_normalize_value():
    assert [normalize_value(v) for v in (True, False, 5, '0x4')] == ['on', 'off', '5', '0x4']


def test_normalize_value_rejects_other_types():
    for bad in (1.5, None, [1], {}):
        with pytest.raises(TypeError):
            normalize_value(bad)


def test_catalogue_scopes():
    assert SETTINGS['dc.maq'] == ('dc', tuple(str(n) for n in range(11)))
    assert SETTINGS['adcs.editf_san'][0] == 'ca'
    assert len(SETTINGS) == 24
    assert {scope for scope, _ in SETTINGS.values()} == {'all', 'dc', 'ca'}


def test_constants():
    assert SETTING_LAYERS == ('all', 'dc', 'server', 'workstation')
    assert GROUP_SCOPES == ('global', 'universal', 'domainlocal')


def test_normalize_value_reads_unquoted_hex_cert_mapping():
    # YAML reads an unquoted 0x4 as the integer 4
    assert normalize_value(4, 'dc.cert_mapping') == '0x4'
    assert normalize_value(4, 'ntlm.lmcompat') == '4'
