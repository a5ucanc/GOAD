import pytest
import yaml

from goad import GoadError
from goad.lab.scenarios import KINDS, load_catalogue, placeholders, substitute, valid_targets
from goad.lab.definition import REPO


def lab(name):
    return yaml.safe_load((REPO / 'labs' / name / 'lab.yml').read_text())


def test_valid_targets_2forests():
    raw = lab('2forests')
    assert valid_targets(raw, 'domain') == ['dc01', 'dc02', 'dc03']
    assert valid_targets(raw, 'server') == ['srv02', 'srv03']
    assert valid_targets(raw, 'ca') == ['dc01', 'srv03']
    assert valid_targets(raw, 'trust') == ['dc01', 'dc03']


def test_valid_targets_1domain_has_no_server():
    assert valid_targets(lab('1domain'), 'server') == []


def test_placeholders_dc02():
    v = placeholders(lab('2domains'), 'dc02')
    assert v['{domain}'] == 'north.sevenkingdoms.local'
    assert v['{netbios}'] == 'NORTH'
    assert v['{dc}'] == 'dc02'
    assert v['{dc_fqdn}'] == 'winterfell.north.sevenkingdoms.local'
    assert v['{target}'] == 'dc02'
    assert v['{target_hostname}'] == 'winterfell'
    assert '{other_forest}' not in v


def test_placeholders_trust():
    assert placeholders(lab('2forests'), 'dc03')['{other_forest}'] == 'sevenkingdoms.local'
    assert placeholders(lab('2forests'), 'dc01')['{other_forest}'] == 'essos.local'


def test_substitute_keys_and_values():
    frag = {'domains': {'{domain}': {'users': {'a': {'description': 'x {netbios}', 'n': 3}}}}}
    out = substitute(frag, {'{domain}': 'd.local', '{netbios}': 'D'})
    assert out == {'domains': {'d.local': {'users': {'a': {'description': 'x D', 'n': 3}}}}}
    assert '{domain}' in frag['domains']


def test_catalogue_loads(tmp_path):
    (tmp_path / 'x.yml').write_text('description: d\ntarget: server\nfragment: {a: 1}\n')
    cat = load_catalogue(tmp_path)
    assert cat['x'].kind == 'server' and cat['x'].fragment == {'a': 1} and 'server' in KINDS


def test_catalogue_rejects_unknown_kind(tmp_path):
    (tmp_path / 'x.yml').write_text('description: d\ntarget: bogus\nfragment: {}\n')
    with pytest.raises(GoadError, match='x.yml'):
        load_catalogue(tmp_path)


def test_catalogue_rejects_unknown_key(tmp_path):
    (tmp_path / 'x.yml').write_text('description: d\ntarget: server\nfragment: {}\nextra: 1\n')
    with pytest.raises(GoadError, match='x.yml'):
        load_catalogue(tmp_path)


def test_catalogue_rejects_non_mapping_fragment(tmp_path):
    (tmp_path / 'x.yml').write_text('description: d\ntarget: server\nfragment: [1]\n')
    with pytest.raises(GoadError, match='x.yml'):
        load_catalogue(tmp_path)
