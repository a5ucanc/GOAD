import pytest
import yaml

from goad import GoadError
from goad.lab import lifecycle, scenario_ops, scenarios
from goad.lab.definition import shipped_lab
from goad.lab.scenarios import Scenario
from goad.state import SnapshotRecord, load_state, save_state, working_lab_path

NORTH = 'north.sevenkingdoms.local'
CATALOGUE = {
    'newuser': Scenario('newuser', 'adds a user', 'domain',
                        {'domains': {'{domain}': {'users': {'scn.user': {'firstname': 'S', 'surname': 'U'}}}}}),
    'srvset': Scenario('srvset', 'server setting', 'server',
                       {'hosts': {'{target}': {'settings': {'smb.signing': 'optional'}}}}),
    'caset': Scenario('caset', 'ca setting', 'ca',
                      {'hosts': {'{target}': {'settings': {'adcs.editf_san': 'on'}}}}),
}


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: CATALOGUE)


def base_text():
    return shipped_lab('2domains').read_text()


def with_entries(*entries, text=None):
    raw = yaml.safe_load(text or base_text())
    if entries:
        raw['scenarios'] = [{'name': n, 'target': t} for n, t in entries]
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def reset(lab, name, wait=None):
        seen.append(('reset', name, working_lab_path(lab.settings).read_text()))
        working_lab_path(lab.settings).write_text(lab.state.snapshot(name).lab_yml)

    def provision(settings, runner, lab, state, tags=None, **kw):
        seen.append(('provision', tags, working_lab_path(settings).read_text()))
        return True

    monkeypatch.setattr('goad.lab.snapshots.reset', reset)
    monkeypatch.setattr('goad.lab.provision.provision', provision)
    return seen


def test_add_entry_default_target():
    text, target = scenario_ops.add_entry(base_text(), 'newuser', None)
    assert target == 'dc01'
    assert yaml.safe_load(text)['scenarios'] == [{'name': 'newuser', 'target': 'dc01'}]
    text, target = scenario_ops.add_entry(text, 'srvset', None)
    assert target == 'srv02'
    assert len(yaml.safe_load(text)['scenarios']) == 2


@pytest.mark.parametrize('name, target, message', [
    ('bogus', None, 'unknown scenario bogus'),
    ('newuser', 'nohost', 'unknown host nohost'),
    ('srvset', 'dc01', "scenario srvset needs a server target: choose one of ['srv02']"),
    ('newuser', 'dc02', 'scenario newuser@dc02 is already enabled'),
])
def test_add_entry_errors(name, target, message):
    text = with_entries(('newuser', 'dc02'))
    with pytest.raises(GoadError) as e:
        scenario_ops.add_entry(text, name, target)
    assert message in str(e.value)


def test_remove_entry_needs_target_when_ambiguous():
    text = with_entries(('newuser', 'dc01'), ('newuser', 'dc02'))
    with pytest.raises(GoadError, match=r"scenario newuser is enabled on dc01, dc02: pass --target"):
        scenario_ops.remove_entry(text, 'newuser', None)
    new, target = scenario_ops.remove_entry(text, 'newuser', 'dc02')
    assert target == 'dc02'
    assert yaml.safe_load(new)['scenarios'] == [{'name': 'newuser', 'target': 'dc01'}]
    new, target = scenario_ops.remove_entry(new, 'newuser', None)
    assert target == 'dc01' and 'scenarios' not in yaml.safe_load(new)


def test_remove_entry_not_enabled():
    with pytest.raises(GoadError, match='scenario newuser is not enabled'):
        scenario_ops.remove_entry(base_text(), 'newuser', None)
    with pytest.raises(GoadError, match='scenario newuser is not enabled'):
        scenario_ops.remove_entry(with_entries(('newuser', 'dc01')), 'newuser', 'dc02')


def _drop_user(text):
    raw = yaml.safe_load(text)
    del raw['domains'][NORTH]['users']['hodor']
    return yaml.safe_dump(raw, sort_keys=False)


def _change_setting(text):
    raw = yaml.safe_load(text)
    raw['settings']['all']['smb.signing'] = 'optional'
    return yaml.safe_dump(raw, sort_keys=False)


def _drop_host_settings(text):
    raw = yaml.safe_load(text)
    del raw['hosts']['dc01']['settings']
    return yaml.safe_dump(raw, sort_keys=False)


@pytest.mark.parametrize('old, new, expected', [
    (base_text, base_text, None),
    (lambda: with_entries(('newuser', 'dc02')), base_text, 'scenarios.newuser@dc02'),
    (base_text, lambda: _drop_user(base_text()), f'domains.{NORTH}.users.hodor'),
    (base_text, lambda: _change_setting(base_text()), None),
    (base_text, lambda: _drop_host_settings(base_text()), 'hosts.dc01.settings.adcs.web_enrollment'),
    (base_text, lambda: with_entries(('newuser', 'dc02')), None),
])
def test_contained_cases(old, new, expected):
    assert scenario_ops.contained(old(), new()) == expected


def _state(*snaps):
    from goad.state import LabState
    return LabState(lab='2domains', ip_range='192.168.56',
                    snapshots=[SnapshotRecord(n, '2026-11-21T00:00:00Z', '', t) for n, t in snaps])


def test_pick_snapshot():
    base = base_text()
    one = with_entries(('newuser', 'dc02'))
    both = with_entries(('newuser', 'dc02'), ('srvset', 'srv02'))
    assert scenario_ops.pick_snapshot(_state(('base', base)), one) == 'base'
    assert scenario_ops.pick_snapshot(_state(('base', base), ('s1', one)), one) == 's1'
    # s2 still holds srvset, which the new text drops: skip it for s1
    assert scenario_ops.pick_snapshot(_state(('base', base), ('s1', one), ('s2', both)), one) == 's1'
    with pytest.raises(GoadError) as e:
        scenario_ops.pick_snapshot(_state(('base', base)), _drop_user(base))
    assert f'domains.{NORTH}.users.hodor' in str(e.value) and 'since base' in str(e.value)


def test_enable_writes_then_provisions(settings, fake, deployed, calls):
    assert scenario_ops.enable(settings, fake, 'newuser', 'dc02') == 'dc02'
    written = working_lab_path(settings).read_text()
    assert yaml.safe_load(written)['scenarios'] == [{'name': 'newuser', 'target': 'dc02'}]
    assert calls == [('provision', scenario_ops.ENABLE_TAGS, written)]
    assert scenario_ops.ENABLE_TAGS == ['content', 'local_groups', 'settings']


def test_enable_error_writes_nothing(settings, fake, deployed, calls):
    before = working_lab_path(settings).read_text()
    with pytest.raises(GoadError):
        scenario_ops.enable(settings, fake, 'srvset', 'dc01')
    assert working_lab_path(settings).read_text() == before and calls == []


def test_enable_failure_keeps_entry(settings, fake, deployed, monkeypatch):
    def boom(*a, **k):
        raise GoadError('ansible-playbook failed')
    monkeypatch.setattr('goad.lab.provision.provision', boom)
    with pytest.raises(GoadError) as e:
        scenario_ops.enable(settings, fake, 'newuser', 'dc02')
    assert str(e.value) == ('ansible-playbook failed: scenario newuser@dc02 stays in lab.yml: run goad lab provision, '
                            'or goad scenario disable newuser --target dc02')
    assert yaml.safe_load(working_lab_path(settings).read_text())['scenarios'] == [{'name': 'newuser', 'target': 'dc02'}]


def _set_working(settings, text):
    working_lab_path(settings).write_text(text)


def test_disable_refuses_before_reset(settings, fake, deployed, calls):
    text = with_entries(('newuser', 'dc02'), text=_drop_user(base_text()))
    _set_working(settings, text)
    asked = []
    with pytest.raises(GoadError) as e:
        scenario_ops.disable(settings, fake, 'newuser', None, yes=True, ask=lambda q, y: asked.append(q) or True)
    assert f'domains.{NORTH}.users.hodor' in str(e.value)
    assert calls == [] and asked == []
    assert working_lab_path(settings).read_text() == text


def test_disable_cancelled(settings, fake, deployed, calls):
    text = with_entries(('newuser', 'dc02'))
    _set_working(settings, text)
    with pytest.raises(GoadError, match='cancelled'):
        scenario_ops.disable(settings, fake, 'newuser', None, yes=False, ask=lambda q, y: False)
    assert calls == [] and working_lab_path(settings).read_text() == text


def test_disable_resets_then_writes_then_provisions(settings, fake, deployed, calls):
    text = with_entries(('newuser', 'dc02'), ('srvset', 'srv02'))
    _set_working(settings, text)
    asked = []
    snap = scenario_ops.disable(settings, fake, 'newuser', 'dc02', yes=False,
                                ask=lambda q, y: asked.append(q) or True)
    assert snap == 'base'
    assert asked == ['Reset the lab to snapshot base and replay the remaining scenarios? '
                     'Changes made inside the VMs since base are lost.']
    expected = with_entries(('srvset', 'srv02'))
    assert [c[0] for c in calls] == ['reset', 'provision']
    assert calls[0][1] == 'base' and calls[1][1] == scenario_ops.ENABLE_TAGS
    assert calls[1][2] == expected == working_lab_path(settings).read_text()


def test_disable_skips_provision_when_identical(settings, fake, deployed, calls):
    _set_working(settings, with_entries(('newuser', 'dc02')))
    assert scenario_ops.disable(settings, fake, 'newuser', None, yes=True, ask=lambda q, y: True) == 'base'
    assert [c[0] for c in calls] == ['reset']
    assert 'scenarios' not in yaml.safe_load(working_lab_path(settings).read_text())


def test_listing():
    rows = scenario_ops.listing(with_entries(('newuser', 'dc02')))
    assert ('newuser', 'domain', 'adds a user', 'dc01, dc02', 'dc02') in rows
    assert ('srvset', 'server', 'server setting', 'srv02', '') in rows
    assert [r[0] for r in rows] == sorted(CATALOGUE)
    assert scenario_ops.listing(None)[0][3:] == ('', '')


def test_scenario_accounts_password():
    raw = yaml.safe_load(with_entries(('newuser', 'dc02')))
    raw['domains'][NORTH]['users']['scn.user'] = {'firstname': 'S', 'surname': 'U', 'password': 'P@ss1'}
    text = yaml.safe_dump(raw, sort_keys=False)
    assert scenario_ops.scenario_accounts(text) == [('NORTH\\scn.user', 'P@ss1', 'scenario newuser@dc02')]


def test_creds_lists_scenario_users(lab, settings):
    _set_working(settings, with_entries(('newuser', 'dc02')))
    rows = lifecycle.creds(lab, laps=lambda *a: 'x')
    assert rows[-1] == lifecycle.Credential('NORTH\\scn.user', 'Aa1234567890!', 'scenario newuser@dc02')
