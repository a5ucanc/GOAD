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
    text = shipped_lab('1domain').read_text().replace("octet: 22,", "octet: 22, services: {mssql: {ssms: true}},")
    lab = parse_lab(text, 'lab.yml')
    assert lab.hosts['srv02'].services == {'mssql': {'ssms': True}}
    entry = render_inventory(lab, '192.168.56')['all']['children']['server']['hosts']['srv02']
    assert entry['services'] == {'mssql': {'ssms': True}}


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


SQL_HOSTS = {'1domain': {'srv02': 'sevenkingdoms.local'}, '2domains': {'srv02': 'north.sevenkingdoms.local'},
             '2forests': {'srv02': 'north.sevenkingdoms.local', 'srv03': 'essos.local'}}


@pytest.mark.parametrize('name', LAB_NAMES)
def test_mssql_and_iis_extensions(name):
    text = shipped_lab(name).read_text() + 'extensions: [mssql, iis]\n'
    lab = parse_lab(text, 'lab.yml')
    base = load_lab(shipped_lab(name))
    assert set(lab.hosts) == set(base.hosts)   # no VM
    for host, domain in SQL_HOSTS[name].items():
        assert lab.hosts[host].services['mssql'] == ({'ssms': True} if host == 'srv02' else {})
        user = lab.domains[domain].users['sql_svc']
        assert user.password == 'Aa1234567890!'
    assert lab.hosts['srv02'].services['iis'] == {}
    assert [h for h in lab.hosts if lab.hosts[h].services] == list(SQL_HOSTS[name])
    raw = yaml.safe_load(text)
    assert extension_hosts(raw, 'mssql') == [] and extension_hosts(raw, 'iis') == []
    entry = render_inventory(lab, '192.168.56')['all']['children']['server']['hosts']['srv02']
    assert entry['services'] == {'mssql': {'ssms': True}, 'iis': {}}


def test_mssql_extension_lists_sql_svc_credential():
    creds = load_catalogue()['mssql'].credentials
    assert any(account.endswith('sql_svc') and password == 'Aa1234567890!' for account, password, _ in creds)


def _svc(services):
    return shipped_lab('2forests').read_text().replace(
        "srv03: {hostname: braavos,", "srv03: {services: {mssql: {}}, hostname: braavos,").replace(
        "octet: 22,", f"octet: 22, services: {services},")


@pytest.mark.parametrize('services, message', [
    ('{mssql: {bogus: 1}}', 'unknown keys'),
    ('{mssql: {ssms: yes please}}', 'ssms'),
    ('{mssql: {sysadmins: x}}', 'sysadmins'),
    ('{mssql: {impersonate_login: [{login: sa}]}}', 'impersonate_login'),
    ('{mssql: {impersonate_user: [{database: msdb, user: dbo}]}}', 'impersonate_user'),
    ('{mssql: {linked: [{name: B, remote: nope, local_login: a, remote_login: sa}]}}', 'nope'),
    ('{mssql: {linked: [{name: B, remote: dc01, local_login: a, remote_login: sa}]}}', 'dc01'),
    ('{mssql: {linked: [{name: B, remote: srv03}]}}', 'linked'),
    ('{iis: {upload: 1}}', 'upload'),
    ('{iis: {bogus: true}}', 'unknown keys'),
])
def test_service_options_validated(services, message):
    with pytest.raises(GoadError, match=message):
        parse_lab(_svc(services), 'lab.yml')


def test_service_options_accepted():
    lab = parse_lab(_svc("{mssql: {ssms: true, sysadmins: ['NORTH\\a'], impersonate_login: [{login: sa, grantee: 'NORTH\\b'}], "
                         "impersonate_user: [{database: msdb, user: dbo, grantee: 'NORTH\\c'}], "
                         "linked: [{name: BRAAVOS, remote: srv03, local_login: 'NORTH\\d', remote_login: sa}]}, "
                         "iis: {upload: true}}"), 'lab.yml')
    assert lab.hosts['srv02'].services['iis'] == {'upload': True}


# Global Constraints: key -> (hostname, os, role, domain, octet, cpus, memory)
VM_HOSTS = {'ws01': ('casterlyrock', 'win11', 'workstation', 'sevenkingdoms.local', 31, 2, 4096),
            'lx01': ('lx01', 'ubuntu2404', 'linux', 'sevenkingdoms.local', 32, 1, 1024),
            'kali': ('kali', 'kali', 'linux', None, 99, 2, 4096)}


@pytest.mark.parametrize('name', LAB_NAMES)
def test_ws01_lx01_kali_extensions(name):
    text = shipped_lab(name).read_text() + 'extensions: [ws01, lx01, kali]\n'
    lab = parse_lab(text, 'lab.yml')
    base = load_lab(shipped_lab(name))
    assert set(lab.hosts) - set(base.hosts) == set(VM_HOSTS)
    for key, (hostname, os_name, role, domain, octet, cpus, memory) in VM_HOSTS.items():
        h = lab.hosts[key]
        assert (h.hostname, h.os, h.role, h.domain, h.octet, h.cpus, h.memory) == (
            hostname, os_name, role, domain, octet, cpus, memory)
    raw = yaml.safe_load(text)
    for key in VM_HOSTS:
        assert extension_hosts(raw, key) == [key]
    children = render_inventory(lab, '192.168.56')['all']['children']
    assert set(children['linux']['hosts']) == {'lx01', 'kali'}
    for group in ('windows', 'workstation', 'member'):
        assert 'ws01' in children[group]['hosts']
    assert 'lx01' not in children['member']['hosts'] and 'kali' not in children['member']['hosts']


@pytest.mark.parametrize('name', LAB_NAMES)
def test_ws01_is_hardened(name):
    lab = parse_lab(shipped_lab(name).read_text() + 'extensions: [ws01]\n', 'lab.yml')
    ws01 = lab.hosts['ws01']
    assert ws01.laps
    assert ws01.local_groups == {
        'Administrators': ('SEVENKINGDOMS\\tywin.lannister', 'SEVENKINGDOMS\\jaime.lannister'),
        'Remote Desktop Users': ('SEVENKINGDOMS\\Lannister',)}
    settings = lab.effective_settings('ws01')
    assert settings['lsa.ppl'] == 'on'
    assert settings['defender.asr_lsass'] == 'block'
    assert settings['defender.asr_psexec_wmi'] == 'block'
    assert settings['powershell.execution_policy'] == 'remotesigned'
    assert settings['host.tier'] == '2'
    assert 'casterlyrock' in render_inventory(lab, '192.168.56')['all']['vars']['goad_domains'][
        'sevenkingdoms.local']['laps_hosts']


@pytest.mark.parametrize('name', LAB_NAMES)
def test_lx01_login_groups(name):
    lab = parse_lab(shipped_lab(name).read_text() + 'extensions: [lx01]\n', 'lab.yml')
    assert lab.hosts['lx01'].local_groups == {'sudoers': ('SEVENKINGDOMS\\Baratheon',),
                                              'ssh': ('SEVENKINGDOMS\\Lannister', 'SEVENKINGDOMS\\Baratheon')}
    entry = render_inventory(lab, '192.168.56')['all']['children']['linux']['hosts']['lx01']
    assert entry['local_groups']['ssh'] == ['SEVENKINGDOMS\\Lannister', 'SEVENKINGDOMS\\Baratheon']
    assert entry['goad_settings'] == {}


def test_linux_local_groups_only_sudoers_and_ssh():
    text = shipped_lab('1domain').read_text() + (
        "  lx: {hostname: lx, os: ubuntu2404, role: linux, domain: sevenkingdoms.local, octet: 40, cpus: 1, "
        "memory: 1024, local_groups: {Administrators: ['SEVENKINGDOMS\\Lannister']}}\n")
    with pytest.raises(GoadError, match='sudoers, ssh'):
        parse_lab(text, 'lab.yml')


def test_linux_local_groups_need_a_domain():
    text = shipped_lab('1domain').read_text() + (
        "  lx: {hostname: lx, os: ubuntu2404, role: linux, octet: 40, cpus: 1, "
        "memory: 1024, local_groups: {ssh: ['SEVENKINGDOMS\\Lannister']}}\n")
    with pytest.raises(GoadError, match='domain'):
        parse_lab(text, 'lab.yml')


def test_kali_extension_lists_kali_credential():
    assert load_catalogue()['kali'].credentials == (('kali', 'kali', 'ssh {range}.99'),)


# Global Constraints: the monitoring servers, not domain joined
MONITORING_HOSTS = {'elk': ('elk', 'ubuntu2404', 'linux', None, 50, 2, 6144),
                    'wazuh': ('wazuh', 'ubuntu2404', 'linux', None, 51, 2, 8192)}


@pytest.mark.parametrize('name', LAB_NAMES)
def test_elk_and_wazuh_extensions(name):
    text = shipped_lab(name).read_text() + 'extensions: [elk, wazuh]\n'
    lab = parse_lab(text, 'lab.yml')
    base = load_lab(shipped_lab(name))
    assert set(lab.hosts) - set(base.hosts) == set(MONITORING_HOSTS)
    for key, (hostname, os_name, role, domain, octet, cpus, memory) in MONITORING_HOSTS.items():
        h = lab.hosts[key]
        assert (h.hostname, h.os, h.role, h.domain, h.octet, h.cpus, h.memory) == (
            hostname, os_name, role, domain, octet, cpus, memory)
        assert h.services == {key: {}}
    raw = yaml.safe_load(text)
    for key in MONITORING_HOSTS:
        assert extension_hosts(raw, key) == [key]
    inv = render_inventory(lab, '192.168.56')
    assert inv['all']['vars']['goad_extensions'] == ['elk', 'wazuh']
    children = inv['all']['children']
    assert set(children['linux']['hosts']) == set(MONITORING_HOSTS)
    assert children['linux']['hosts']['elk']['services'] == {'elk': {}}
    assert children['linux']['hosts']['wazuh']['ansible_host'] == '192.168.56.51'
    assert not set(MONITORING_HOSTS) & set(children['member']['hosts'])


def test_elk_and_wazuh_credentials_render_with_the_range():
    from goad.lab.lifecycle import _extension_credentials
    text = shipped_lab('1domain').read_text() + 'extensions: [elk, wazuh]\n'
    rows = [(c.account, c.password, c.scope) for c in _extension_credentials(text, '10.2.0')]
    assert rows == [('elastic', 'Aa1234567890!', 'elk (http://10.2.0.50:5601)'),
                    ('admin', 'Aa1234567890!', 'wazuh (https://10.2.0.51)')]
