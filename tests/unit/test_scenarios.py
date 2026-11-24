import pytest
import yaml

from goad import GoadError
from goad.lab.scenarios import KINDS, Scenario, expand, load_catalogue, placeholders, substitute, valid_targets
from goad.lab.definition import REPO


def lab(name):
    return yaml.safe_load((REPO / 'labs' / name / 'lab.yml').read_text())


def test_valid_targets_2forests():
    raw = lab('2forests')
    assert valid_targets(raw, 'domain') == ['dc01', 'dc02', 'dc03']
    assert valid_targets(raw, 'server') == ['srv02', 'srv03']
    assert valid_targets(raw, 'ca') == ['dc01', 'srv03']
    assert valid_targets(raw, 'trust') == ['dc01', 'dc03']


def test_valid_targets_1domain_server_is_srv02():
    assert valid_targets(lab('1domain'), 'server') == ['srv02']


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


NORTH = 'north.sevenkingdoms.local'


def _sc(fragment, kind='domain'):
    return Scenario('t', '', kind, fragment)


def _user(**kw):
    u = {'firstname': 'A', 'surname': 'B'}
    u.update(kw)
    return {'domains': {'{domain}': {'users': {'new.user': u}}}}


def _with(*entries):
    raw = lab('2domains')
    raw['scenarios'] = [{'name': n, 'target': t} for n, t in entries]
    return raw


def test_expand_without_scenarios_is_identity():
    raw = lab('2domains')
    out = expand(raw, 'x', {})
    assert out == raw and out is not raw
    raw['scenarios'] = []
    assert expand(raw, 'x', {}) == raw


def test_expand_adds_user_to_target_domain():
    out = expand(_with(('t', 'dc02')), 'x', {'t': _sc(_user())})
    assert out['domains'][NORTH]['users']['new.user']['firstname'] == 'A'
    assert 'new.user' not in out['domains']['sevenkingdoms.local']['users']


def test_expand_does_not_mutate_input():
    raw = _with(('t', 'dc02'))
    before = copy_deep(raw)
    expand(raw, 'x', {'t': _sc(_user())})
    assert raw == before


def copy_deep(x):
    import copy
    return copy.deepcopy(x)


def test_list_union():
    frag = {'domains': {'{domain}': {'users': {'arya.stark': {'groups': ['Night Watch', 'Stark']}}}}}
    cat = {'a': _sc(frag), 'b': _sc(frag)}
    out = expand(_with(('a', 'dc02'), ('b', 'dc02')), 'x', cat)
    assert out['domains'][NORTH]['users']['arya.stark']['groups'] == ['Stark', 'Night Watch']


def test_setting_overrides_lab_value():
    raw = _with(('t', 'dc01'))
    raw['hosts']['dc01']['settings'] = {'adcs.web_enrollment': 'off'}
    out = expand(raw, 'x', {'t': _sc({'hosts': {'{target}': {'settings': {'adcs.web_enrollment': 'on'}}}})})
    assert out['hosts']['dc01']['settings']['adcs.web_enrollment'] == 'on'


def test_two_scenarios_conflict_on_setting():
    mk = lambda v: _sc({'hosts': {'{target}': {'settings': {'dc.maq': v}}}})
    with pytest.raises(GoadError) as e:
        expand(_with(('a', 'dc01'), ('b', 'dc01')), 'x', {'a': mk(5), 'b': mk(10)})
    msg = str(e.value)
    assert 'b@dc01' in msg and 'a@dc01' in msg and 'hosts.dc01.settings.dc.maq' in msg


def test_fragment_conflicts_with_lab_object():
    frag = {'domains': {'sevenkingdoms.local': {'users': {'tywin.lannister': {'description': 'Other'}}}}}
    with pytest.raises(GoadError, match='already set by lab.yml'):
        expand(_with(('t', 'dc01')), 'x', {'t': _sc(frag)})


def test_same_value_twice_is_fine():
    frag = {'hosts': {'{target}': {'settings': {'dc.maq': 10}}}}
    out = expand(_with(('a', 'dc01'), ('b', 'dc01')), 'x', {'a': _sc(frag), 'b': _sc(frag)})
    assert out['hosts']['dc01']['settings']['dc.maq'] == 10


def test_non_settings_conflict_between_entries_names_owner():
    mk = lambda d: _sc(_user(description=d))
    with pytest.raises(GoadError, match='scenario b@dc02 sets .*, already set by scenario a@dc02'):
        expand(_with(('a', 'dc02'), ('b', 'dc02')), 'x', {'a': mk('x'), 'b': mk('y')})


@pytest.mark.parametrize('scenarios, message', [
    ('nope', 'scenarios must be a list'),
    ([{'name': 't'}], 'scenarios must be a list'),
    ([{'name': 't', 'target': 'dc01', 'x': 1}], 'scenarios must be a list'),
    (['t'], 'scenarios must be a list'),
    ([{'name': 't', 'target': 5}], 'scenarios must be a list'),
    ([{'name': ['t'], 'target': 'dc01'}], 'scenarios must be a list'),
    ([{'name': 'zzz', 'target': 'dc01'}], "unknown scenario 'zzz'"),
    ([{'name': 't', 'target': 'nohost'}], "unknown host 'nohost' in scenario t"),
    ([{'name': 'srv', 'target': 'dc01'}], 'scenario srv needs a server target: choose one of'),
    ([{'name': 'tr', 'target': 'dc01'}], 'scenario tr needs a trust target: none in this lab'),
    ([{'name': 't', 'target': 'dc01'}, {'name': 't', 'target': 'dc01'}], 'duplicate entry t@dc01'),
])
def test_expand_errors(scenarios, message):
    raw = lab('2domains')
    raw['scenarios'] = scenarios
    cat = {'t': _sc({}), 'srv': _sc({}, 'server'), 'tr': _sc({}, 'trust')}
    with pytest.raises(GoadError, match=message) as e:
        expand(raw, 'SRC', cat)
    assert str(e.value).startswith('SRC: ')


def test_load_catalogue_bad_yaml_names_file(tmp_path):
    (tmp_path / 'bad.yml').write_text('a: [unclosed\n')
    with pytest.raises(GoadError, match='bad.yml'):
        load_catalogue(tmp_path)


def test_equal_setting_records_owner_so_later_value_conflicts():
    raw = _with(('a', 'dc01'), ('b', 'dc01'))
    raw['hosts']['dc01']['settings'] = {'dc.maq': 5}
    mk = lambda v: _sc({'hosts': {'{target}': {'settings': {'dc.maq': v}}}})
    with pytest.raises(GoadError) as e:
        expand(raw, 'x', {'a': mk(5), 'b': mk(10)})
    assert 'a@dc01' in str(e.value) and 'b@dc01' in str(e.value)


def _merge_expand(first, second):
    # {target} and {dc} both substitute to dc02, so the two keys collide
    frag = {'hosts': {'{target}': first, '{dc}': second}}
    return expand(_with(('t', 'dc02')), 'x', {'t': _sc(frag)})


def test_key_collision_list_union():
    out = _merge_expand({'tags': ['x']}, {'tags': ['y']})
    assert out['hosts']['dc02']['tags'] == ['x', 'y']


def test_key_collision_equal_scalar_fine():
    out = _merge_expand({'note': 'A'}, {'note': 'A'})
    assert out['hosts']['dc02']['note'] == 'A'


def test_key_collision_conflicting_scalar_raises():
    with pytest.raises(GoadError, match='conflict'):
        _merge_expand({'note': 'A'}, {'note': 'Z'})


def test_key_collision_mismatched_container_raises():
    with pytest.raises(GoadError, match='conflict'):
        _merge_expand({'tags': ['x']}, {'tags': 'x'})


def test_setting_str_equal_is_not_a_conflict():
    mk = lambda v: _sc({'hosts': {'{target}': {'settings': {'dc.strong_cert_binding': v}}}})
    out = expand(_with(('a', 'dc01'), ('b', 'dc01')), 'x', {'a': mk('0'), 'b': mk(0)})
    assert str(out['hosts']['dc01']['settings']['dc.strong_cert_binding']) == '0'


def _tmp_catalogues(tmp_path, monkeypatch, scenario_data):
    from goad.lab import extensions, scenarios as scn
    ext_dir, scn_dir = tmp_path / 'ext', tmp_path / 'scn'
    ext_dir.mkdir()
    scn_dir.mkdir()
    svc = {'services': {'mssql': {}}}
    (ext_dir / 'mssql.yml').write_text(yaml.safe_dump({'description': 'mssql', 'labs': {
        '2forests': {'hosts': {'srv03': svc, 'srv02': svc}}}}), encoding='utf-8')
    (scn_dir / 'dbscn.yml').write_text(yaml.safe_dump(scenario_data), encoding='utf-8')
    monkeypatch.setattr(extensions, 'EXTENSION_DIR', ext_dir)
    monkeypatch.setattr(scn, 'SCENARIO_DIR', scn_dir)


DBSCN = {'description': 'db thing', 'target': 'service:mssql', 'requires': 'mssql',
         'fragment': {'hosts': {'{target}': {'settings': {'smb.signing': 'optional'}}}}}


def test_requires_refused_without_extension(tmp_path, monkeypatch):
    _tmp_catalogues(tmp_path, monkeypatch, DBSCN)
    raw = lab('2forests')
    raw['scenarios'] = [{'name': 'dbscn', 'target': 'srv02'}]
    with pytest.raises(GoadError) as e:
        expand(raw, 'lab.yml')
    assert str(e.value) == 'lab.yml: scenario dbscn needs extension mssql: run goad extension add mssql'


def test_service_kind_targets_srv02_first(tmp_path, monkeypatch):
    from goad.lab import extensions
    _tmp_catalogues(tmp_path, monkeypatch, DBSCN)
    raw = lab('2forests')
    raw['extensions'] = ['mssql']
    assert valid_targets(extensions.expand(raw, 'lab.yml'), 'service:mssql') == ['srv02', 'srv03']
    assert valid_targets(lab('2forests'), 'service:mssql') == []


def test_listing_shows_requires(tmp_path, monkeypatch):
    from goad.lab import scenario_ops
    _tmp_catalogues(tmp_path, monkeypatch, DBSCN)
    assert load_catalogue()['dbscn'].requires == 'mssql'
    raw = lab('2forests')
    raw['extensions'] = ['mssql']
    rows = scenario_ops.listing(yaml.safe_dump(raw))
    assert rows == [('dbscn', 'service:mssql', 'db thing (requires extension mssql)', 'srv02, srv03', '')]


def test_add_entry_requires_and_expands_extension(tmp_path, monkeypatch):
    from goad.lab import scenario_ops
    _tmp_catalogues(tmp_path, monkeypatch, DBSCN)
    raw = lab('2forests')
    with pytest.raises(GoadError, match='needs extension mssql: run goad extension add mssql'):
        scenario_ops.add_entry(yaml.safe_dump(raw), 'dbscn', None)
    raw['extensions'] = ['mssql']
    _, target = scenario_ops.add_entry(yaml.safe_dump(raw), 'dbscn', None)
    assert target == 'srv02'


def test_targets_skip_fragment_naming_missing_host():
    from goad.lab.scenarios import targets
    sc = _sc({'hosts': {'srv02': {'settings': {'smb.signing': 'optional'}}, 'srv03': {'settings': {'smb.signing': 'optional'}}}},
             kind='server')
    assert targets(lab('2domains'), sc) == []
    # target-independent fragment: one entry, on the first kind target
    assert targets(lab('2forests'), sc) == ['srv02']


def test_targets_keep_target_dependent_fragments():
    from goad.lab.scenarios import targets
    sc = _sc({'hosts': {'{target}': {'settings': {'smb.signing': 'optional'}}}}, kind='server')
    assert targets(lab('2forests'), sc) == valid_targets(lab('2forests'), 'server')


def test_expand_refuses_duplicate_target_independent_entry():
    sc = _sc({'hosts': {'srv02': {'settings': {'smb.signing': 'optional'}}}}, kind='server')
    raw = lab('2forests')
    raw['scenarios'] = [{'name': 'a', 'target': 'srv03'}]
    with pytest.raises(GoadError, match=r"choose one of \['srv02'\]"):
        expand(raw, 'x', {'a': sc})
