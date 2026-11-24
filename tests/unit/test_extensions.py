import pytest
import yaml

from goad import GoadError
from goad.lab import extensions, scenarios
from goad.lab.definition import LAB_NAMES, load_lab, parse_lab, shipped_lab
from goad.lab.extensions import Extension, entries, expand, extension_hosts, load_catalogue
from goad.lab.inventory import render_inventory

X = {'hostname': 'xhost', 'os': 'win2022', 'role': 'server', 'domain': 'sevenkingdoms.local',
     'octet': 40, 'cpus': 2, 'memory': 4096}


def _write(directory, name, data):
    (directory / f'{name}.yml').write_text(yaml.safe_dump(data), encoding='utf-8')


def _ext(host=None, lab='1domain', **extra):
    return {'description': 'test', 'labs': {lab: {'hosts': {'x': dict(X, **(host or {}))}}}, **extra}


def _text(*names):
    return shipped_lab('1domain').read_text() + f'extensions: [{", ".join(names)}]\n'


@pytest.fixture
def catdir(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, 'EXTENSION_DIR', tmp_path)
    return tmp_path


def test_load_catalogue(catdir):
    _write(catdir, 'a', _ext(credentials=[{'account': 'kali', 'password': 'kali', 'scope': 'ssh {range}.99'}]))
    cat = load_catalogue()
    assert cat['a'] == Extension('a', 'test', {'1domain': {'hosts': {'x': X}}},
                                 (('kali', 'kali', 'ssh {range}.99'),))


@pytest.mark.parametrize('data, message', [
    ({'labs': {}, 'x': 1}, 'unknown keys'),
    ({'description': 'd'}, 'labs must be a mapping'),
    ({'description': 'd', 'labs': {'1domain': []}}, 'labs must be a mapping'),
    ({'description': 'd', 'labs': {}, 'credentials': [{'account': 'a'}]}, 'credentials must be a list'),
    ([1], 'must be a mapping'),
])
def test_load_catalogue_errors(catdir, data, message):
    _write(catdir, 'a', data)
    with pytest.raises(GoadError, match=message):
        load_catalogue()


def test_expand_adds_host_and_lists_extension(catdir):
    _write(catdir, 'a', _ext())
    lab = parse_lab(_text('a'), 'lab.yml')
    assert lab.hosts['x'].octet == 40 and lab.extensions == ('a',)


def test_extension_not_for_lab_refused(catdir):
    _write(catdir, 'a', _ext(lab='2domains'))
    with pytest.raises(GoadError, match='extension a does not apply to lab 1domain'):
        parse_lab(_text('a'), 'lab.yml')


def test_unknown_extension_refused(catdir):
    with pytest.raises(GoadError, match='extension zz does not apply to lab 1domain'):
        parse_lab(_text('zz'), 'lab.yml')


@pytest.mark.parametrize('value', ['a', [1], ['a', 'a'], {'a': 1}])
def test_entries_must_be_unique_strings(value):
    with pytest.raises(GoadError, match='extensions'):
        entries({'extensions': value})


def test_entries_default_empty():
    assert entries({}) == [] and entries({'extensions': None}) == []


def test_two_extensions_same_host_identical_merge(catdir):
    _write(catdir, 'a', _ext())
    _write(catdir, 'b', _ext())
    lab = parse_lab(_text('a', 'b'), 'lab.yml')
    assert lab.hosts['x'].memory == 4096 and lab.extensions == ('a', 'b')


def test_two_extensions_same_host_conflict(catdir):
    _write(catdir, 'a', _ext())
    _write(catdir, 'b', _ext({'memory': 8192}))
    with pytest.raises(GoadError, match='extension b sets hosts.x.memory, already set by extension a'):
        parse_lab(_text('a', 'b'), 'lab.yml')


def test_extension_conflict_with_lab_yml(catdir):
    _write(catdir, 'a', {'description': 'd', 'labs': {'1domain': {'hosts': {'srv02': {'memory': 1}}}}})
    with pytest.raises(GoadError, match='extension a sets hosts.srv02.memory, already set by lab.yml'):
        parse_lab(_text('a'), 'lab.yml')


def test_extensions_expand_before_scenarios(catdir, monkeypatch):
    _write(catdir, 'a', _ext())
    frag = {'hosts': {'{target}': {'local_groups': {'Administrators': ['{netbios}\\Lannister']}}}}
    monkeypatch.setattr(scenarios, 'load_catalogue',
                        lambda *a, **k: {'s': scenarios.Scenario('s', '', 'server', frag)})
    lab = parse_lab(_text('a') + 'scenarios:\n  - {name: s, target: x}\n', 'lab.yml')
    assert lab.hosts['x'].local_groups == {'Administrators': ('SEVENKINGDOMS\\Lannister',)}
    assert lab.scenarios[0].target == 'x'


def test_expand_without_extensions_is_identity():
    raw = yaml.safe_load(shipped_lab('1domain').read_text())
    assert expand(raw, 'x', {}) == raw


def test_extension_hosts_excludes_shared(catdir):
    _write(catdir, 'a', _ext())
    _write(catdir, 'b', {'description': 'd', 'labs': {'1domain': {'hosts': {'x': X, 'y': dict(X, octet=41)}}}})
    raw = yaml.safe_load(_text('a', 'b'))
    assert extension_hosts(raw, 'b') == ['y']
    assert extension_hosts(raw, 'a') == []
    raw['extensions'] = ['a']
    assert extension_hosts(raw, 'a') == ['x']


def test_extension_hosts_excludes_lab_hosts(catdir):
    _write(catdir, 'a', {'description': 'd', 'labs': {'1domain': {'hosts': {'srv02': {'memory': 4096}, 'x': X}}}})
    raw = yaml.safe_load(_text('a'))
    assert extension_hosts(raw, 'a') == ['x']


def test_services_parse():
    text = shipped_lab('1domain').read_text().replace("octet: 22,", "octet: 22, services: {mssql: {sa: x}},")
    lab = parse_lab(text, 'lab.yml')
    assert lab.hosts['srv02'].services == {'mssql': {'sa': 'x'}}
    entry = render_inventory(lab, '192.168.56')['all']['children']['server']['hosts']['srv02']
    assert entry['services'] == {'mssql': {'sa': 'x'}}


def test_services_unknown_name_refused():
    text = shipped_lab('1domain').read_text().replace("octet: 22,", "octet: 22, services: {ftp: {}},")
    with pytest.raises(GoadError, match='ftp'):
        parse_lab(text, 'lab.yml')


def test_services_value_must_be_mapping():
    text = shipped_lab('1domain').read_text().replace("octet: 22,", "octet: 22, services: {iis: 1},")
    with pytest.raises(GoadError, match='iis'):
        parse_lab(text, 'lab.yml')


def test_inventory_lists_extensions(catdir):
    _write(catdir, 'a', _ext())
    inv = render_inventory(parse_lab(_text('a'), 'lab.yml'), '192.168.56')
    assert inv['all']['vars']['goad_extensions'] == ['a']
    assert 'x' in inv['all']['children']['member']['hosts']


@pytest.mark.parametrize('name', LAB_NAMES)
def test_inventory_unchanged_without_extensions(name):
    lab = load_lab(shipped_lab(name))
    assert lab.extensions == ()
    inv = render_inventory(lab, '192.168.56')
    assert 'goad_extensions' not in inv['all']['vars']
    assert all('services' not in h for g in inv['all']['children'].values() for h in g['hosts'].values())


def test_os_kali_is_linux():
    from goad.settings import OS_NAMES
    from goad.templates.store import OS_FAMILY
    assert 'kali' in OS_NAMES and OS_FAMILY['kali'] == 'linux'
