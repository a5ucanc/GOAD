import pytest
import yaml

from goad import GoadError
from goad.host.runner import Result
from goad.lab import deploy as deploy_module
from goad.lab import extension_ops, extensions, lifecycle, scenario_ops, scenarios
from goad.lab.deploy import Probes
from goad.lab.definition import shipped_lab
from goad.lab.scenarios import Scenario
from goad.state import HostState, SnapshotRecord, load_state, save_state, working_lab_path

from tests.unit.test_deploy import CloneRunner, FakeStore

X = {'hostname': 'xhost', 'os': 'win2022', 'role': 'server', 'domain': 'sevenkingdoms.local',
     'octet': 40, 'cpus': 2, 'memory': 4096}
X_IP = '192.168.56.40'
CATALOGUE = {
    'srvset': Scenario('srvset', 'server setting', 'server',
                       {'hosts': {'{target}': {'settings': {'smb.signing': 'optional'}}}}),
}


def _write_ext(directory, name, fragment, lab='2domains'):
    data = {'description': f'{name} ext', 'labs': {lab: fragment}}
    (directory / f'{name}.yml').write_text(yaml.safe_dump(data), encoding='utf-8')


@pytest.fixture(autouse=True)
def catdir(tmp_path, monkeypatch):
    directory = tmp_path / 'ext'
    directory.mkdir()
    monkeypatch.setattr(extensions, 'EXTENSION_DIR', directory)
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: CATALOGUE)
    _write_ext(directory, 'a', {'hosts': {'x': X}})
    _write_ext(directory, 'b', {'hosts': {'dc01': {'services': {}}}})
    _write_ext(directory, 'novm', {'hosts': {'srv02': {'services': {}}}})
    _write_ext(directory, 'other', {}, lab='2forests')
    return directory


def base_text():
    return shipped_lab('2domains').read_text()


def text_with(*names, scenario_entries=()):
    raw = yaml.safe_load(base_text())
    if scenario_entries:
        raw['scenarios'] = [{'name': n, 'target': t} for n, t in scenario_entries]
    if names:
        raw['extensions'] = list(names)
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


@pytest.fixture
def env(settings, deployed, tmp_path, monkeypatch):
    def local(path):
        return tmp_path / 'win' / path[3:].replace('\\', '/')

    monkeypatch.setattr(deploy_module, 'to_wsl', local)
    monkeypatch.setattr(lifecycle, 'to_wsl', local)
    for host in deployed.hosts.values():   # the deployed VMs exist on disk
        local(host.vmx).parent.mkdir(parents=True, exist_ok=True)
        local(host.vmx).write_text('displayName = "vm"\n')
    provisions = []

    def provision(settings, runner, lab, state, tags=None, **kw):
        provisions.append((tags, sorted(lab.hosts), working_lab_path(settings).read_text()))
        return True

    probes = Probes(is_up=lambda ip: False, firstboot_marker=lambda vmrun, vmx: 'done', sleep=lambda s: None,
                    wait_port=lambda *a: None, check_psrp=lambda *a: None, check_ssh=lambda *a: None,
                    remove_setup_account=lambda *a: None, provision=provision)
    runner = CloneRunner(local)
    # every VM holds base and the ext-* snapshots; a test inserts a more specific answer in front
    runner.respond(lambda a: a[3] == 'listSnapshots',
                   Result(0, 'Total snapshots: 3\nbase\next-a\next-novm\n', ''))

    class Env:
        pass
    e = Env()
    e.settings, e.runner, e.store, e.probes, e.local, e.provisions = settings, runner, FakeStore(), probes, local, provisions
    return e


def clones(env):
    return [a for a in env.runner.calls if a[3] == 'clone']


# add_entry / remove_entry

def test_add_entry_appends():
    text = extension_ops.add_entry(base_text(), 'a', '2domains')
    assert yaml.safe_load(text)['extensions'] == ['a']
    text = extension_ops.add_entry(text, 'b', '2domains')
    assert yaml.safe_load(text)['extensions'] == ['a', 'b']


@pytest.mark.parametrize('text, name, message', [
    (base_text, 'zzz', 'unknown extension zzz: see goad extension list'),
    (base_text, 'other', 'extension other does not apply to lab 2domains'),
    (lambda: text_with('a'), 'a', 'extension a is already installed'),
])
def test_add_entry_refusals(text, name, message):
    with pytest.raises(GoadError) as e:
        extension_ops.add_entry(text(), name, '2domains')
    assert str(e.value) == message


def test_remove_entry_drops_key_when_empty():
    assert 'extensions' not in yaml.safe_load(extension_ops.remove_entry(text_with('a'), 'a'))
    assert yaml.safe_load(extension_ops.remove_entry(text_with('a', 'b'), 'b'))['extensions'] == ['a']


def test_remove_entry_not_installed():
    with pytest.raises(GoadError, match='extension a is not installed'):
        extension_ops.remove_entry(base_text(), 'a')


def test_remove_refuses_not_last():
    with pytest.raises(GoadError) as e:
        extension_ops.remove_entry(text_with('a', 'b'), 'a')
    assert str(e.value) == 'extension a was added before b: remove b first'


def test_remove_refuses_dependent_scenario():
    text = text_with('a', scenario_entries=[('srvset', 'x'), ('srvset', 'srv02')])
    with pytest.raises(GoadError) as e:
        extension_ops.remove_entry(text, 'a')
    assert str(e.value) == 'scenarios depend on extension a: disable srvset@x first'


def test_remove_refuses_scenario_that_requires_extension(monkeypatch):
    class Requiring:
        kind = 'server'
        requires = 'novm'
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: dict(CATALOGUE, needs=Requiring()))
    raw = yaml.safe_load(text_with('novm'))
    raw['scenarios'] = [{'name': 'needs', 'target': 'srv02'}]
    with pytest.raises(GoadError, match=r'disable needs@srv02 first'):
        extension_ops.remove_entry(yaml.safe_dump(raw, sort_keys=False), 'novm')


# add

def test_add_clones_only_new_hosts_and_snapshots(env):
    record = extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert [c[-1] for c in clones(env)] == ['-cloneName=2domains-x']
    assert [p[0] for p in env.provisions] == [None] and 'x' in env.provisions[0][1]
    state = load_state(env.settings)
    assert record.name == 'ext-a' and [s.name for s in state.snapshots] == ['base', 'ext-a']
    assert state.pending_extension is None
    assert state.hosts['x'].ip == X_IP and state.hosts['x'].ready and state.hosts['x'].template == 'win2022-v1'
    assert yaml.safe_load(working_lab_path(env.settings).read_text())['extensions'] == ['a']


def test_add_vm_less_extension_clones_nothing(env):
    extension_ops.add(env.settings, env.runner, env.store, 'novm', probes=env.probes)
    assert clones(env) == []
    assert len(env.provisions) == 1 and load_state(env.settings).snapshot('ext-novm')


def test_add_resumes_after_failed_provision(env):
    provision = env.probes.provision

    def boom(*a, **k):
        raise GoadError('ansible-playbook failed')
    env.probes.provision = boom
    with pytest.raises(GoadError) as e:
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert str(e.value) == 'ansible-playbook failed: run goad extension add a again to resume'
    state = load_state(env.settings)
    assert state.pending_extension == 'a' and state.hosts['x'].ready and state.snapshot('ext-a') is None
    assert len(clones(env)) == 1
    env.runner.calls.clear()
    env.probes.provision = provision
    extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert clones(env) == [] and len(env.provisions) == 1
    state = load_state(env.settings)
    assert state.pending_extension is None and state.snapshot('ext-a')
    assert yaml.safe_load(working_lab_path(env.settings).read_text())['extensions'] == ['a']


def test_add_resumes_failed_first_boot(env):
    env.probes.firstboot_marker = lambda vmrun, vmx: 'failed: x'
    with pytest.raises(GoadError, match='again to resume'):
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert not load_state(env.settings).hosts['x'].ready
    env.probes.firstboot_marker = lambda vmrun, vmx: 'done'
    extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert load_state(env.settings).hosts['x'].ready and len(clones(env)) == 1


def test_add_reuses_usable_snapshot_from_failed_run(env):
    text = text_with('a')
    state = load_state(env.settings)
    working_lab_path(env.settings).write_text(text)
    state.pending_extension = 'a'
    state.hosts['x'] = HostState(vmx=r'C:\goad\lab\x\x.vmx', template='win2022-v1', hostname='xhost', ip=X_IP, ready=True)
    state.snapshots.append(SnapshotRecord('ext-a', '2026-11-24T00:00:00Z', 'ext-a', text))
    save_state(env.settings, state)
    record = extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert record.taken_at == '2026-11-24T00:00:00Z'
    assert not [a for a in env.runner.calls if a[3] == 'snapshot']
    assert load_state(env.settings).pending_extension is None


def test_add_retakes_usable_snapshot_missing_on_a_recloned_host(env):
    text = text_with('a')
    state = load_state(env.settings)
    working_lab_path(env.settings).write_text(text)
    state.pending_extension = 'a'
    state.snapshots.append(SnapshotRecord('ext-a', '2026-11-24T00:00:00Z', 'ext-a', text))
    save_state(env.settings, state)
    env.runner._responses.insert(0, (lambda a: a[3] == 'listSnapshots' and r'\x\x.vmx' in a[4],
                                     Result(0, 'Total snapshots: 1\nbase\n', '')))
    record = extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert [a for a in env.runner.calls if a[3] == 'deleteSnapshot']
    assert [a for a in env.runner.calls if a[3] == 'snapshot']
    assert load_state(env.settings).pending_extension is None


def test_add_refuses_ip_in_use(env):
    env.probes.is_up = lambda ip: ip == X_IP
    with pytest.raises(GoadError) as e:
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert str(e.value) == f'{X_IP} (x) already answers: run goad extension add a again to resume'
    assert clones(env) == [] and env.provisions == []
    state = load_state(env.settings)
    assert state.pending_extension == 'a' and 'x' not in state.hosts


def test_add_refuses_missing_template(env):
    env.store.templates.pop('win2022')
    with pytest.raises(GoadError, match='no win2022 template: run goad template build win2022'):
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert clones(env) == []


def test_add_missing_kali_template_says_import(env, catdir):
    _write_ext(catdir, 'kali', {'hosts': {'kali': {'hostname': 'kali', 'os': 'kali', 'role': 'linux', 'octet': 99, 'cpus': 2, 'memory': 4096}}})
    with pytest.raises(GoadError, match='no kali template: run goad template import kali'):
        extension_ops.add(env.settings, env.runner, env.store, 'kali', probes=env.probes)


def test_add_refuses_already_installed(env):
    extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    env.runner.calls.clear()
    with pytest.raises(GoadError) as e:
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert str(e.value) == 'extension a is already installed'
    assert clones(env) == []


def test_add_refuses_not_applicable(env):
    before = working_lab_path(env.settings).read_text()
    with pytest.raises(GoadError, match='extension other does not apply to lab 2domains'):
        extension_ops.add(env.settings, env.runner, env.store, 'other', probes=env.probes)
    assert working_lab_path(env.settings).read_text() == before
    assert load_state(env.settings).pending_extension is None


def test_add_refuses_while_another_is_pending(env):
    env.probes.is_up = lambda ip: ip == X_IP
    with pytest.raises(GoadError):
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    with pytest.raises(GoadError) as e:
        extension_ops.add(env.settings, env.runner, env.store, 'novm', probes=env.probes)
    assert str(e.value) == ('extension a is half added or half removed: run goad extension add a '
                            'to resume the add, or goad extension remove a to finish the removal')


def test_add_refuses_undeployed(env):
    state = load_state(env.settings)
    state.step = 'provision'
    save_state(env.settings, state)
    with pytest.raises(GoadError, match='not deployed'):
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)


# remove

@pytest.fixture
def installed(env):
    """Extension a installed after base: VM x exists, snapshot ext-a holds it."""
    text = text_with('a')
    working_lab_path(env.settings).write_text(text)
    state = load_state(env.settings)
    state.hosts['x'] = HostState(vmx=r'C:\goad\lab\x\x.vmx', template='win2022-v1', hostname='xhost', ip=X_IP, ready=True)
    state.snapshots.append(SnapshotRecord('ext-a', '2026-11-24T00:00:00Z', 'ext-a', text))
    state.current = 'ext-a'
    save_state(env.settings, state)
    env.local(state.hosts['x'].vmx).parent.mkdir(parents=True, exist_ok=True)
    return text


@pytest.fixture
def resets(env, monkeypatch):
    seen = []

    def reset(lab, name, wait=None, current_text=None):
        seen.append((name, current_text, len(env.runner.calls), sorted(lab.state.hosts)))
        working_lab_path(lab.settings).write_text(lab.state.snapshot(name).lab_yml)
    monkeypatch.setattr('goad.lab.snapshots.reset', reset)
    return seen


def test_remove_deletes_vms_resets_and_drops_snapshots(env, installed, resets, monkeypatch):
    monkeypatch.setattr('goad.lab.provision.provision', env.probes.provision)
    asked = []
    snap = extension_ops.remove(env.settings, env.runner, 'a', yes=False, ask=lambda q, y: asked.append(q) or True)
    assert snap == 'base'
    assert asked == ['Delete VMs x and reset the lab to snapshot base? '
                     'Changes made inside the VMs since base are lost.']
    deletes = [i for i, a in enumerate(env.runner.calls) if a[3] == 'deleteVM']
    assert len(deletes) == 1 and 'x.vmx' in env.runner.calls[deletes[0]][4]
    new_text = base_text()
    assert len(resets) == 1
    name, current_text, calls_before, hosts = resets[0]
    assert name == 'base' and deletes[0] < calls_before and 'x' not in hosts
    assert 'extensions' not in yaml.safe_load(current_text)
    state = load_state(env.settings)
    assert 'x' not in state.hosts and [s.name for s in state.snapshots] == ['base']
    assert not env.local(r'C:\goad\lab\x\x.vmx').parent.exists()
    assert 'extensions' not in yaml.safe_load(working_lab_path(env.settings).read_text())
    assert yaml.safe_load(working_lab_path(env.settings).read_text()) == yaml.safe_load(new_text)
    assert env.provisions == []   # nothing to replay: base content equals the new lab.yml


def test_remove_replays_scenarios(env, resets, monkeypatch):
    monkeypatch.setattr('goad.lab.provision.provision', env.probes.provision)
    text = text_with('novm', scenario_entries=[('srvset', 'srv02')])
    working_lab_path(env.settings).write_text(text)
    extension_ops.remove(env.settings, env.runner, 'novm', yes=True, ask=lambda q, y: True)
    assert [p[0] for p in env.provisions] == [scenario_ops.ENABLE_TAGS]
    assert yaml.safe_load(working_lab_path(env.settings).read_text())['scenarios'] == [
        {'name': 'srvset', 'target': 'srv02'}]
    assert not [a for a in env.runner.calls if a[3] == 'deleteVM']


def test_remove_without_snapshot_refuses(env, installed, resets):
    state = load_state(env.settings)
    state.snapshots = [s for s in state.snapshots if s.name != 'base']
    save_state(env.settings, state)
    with pytest.raises(GoadError) as e:
        extension_ops.remove(env.settings, env.runner, 'a', yes=True, ask=lambda q, y: True)
    assert str(e.value) == 'no snapshot without extension a: redeploy'
    assert resets == [] and not [a for a in env.runner.calls if a[3] == 'deleteVM']


def test_remove_cancelled(env, installed, resets):
    with pytest.raises(GoadError, match='cancelled'):
        extension_ops.remove(env.settings, env.runner, 'a', yes=False, ask=lambda q, y: False)
    assert resets == [] and 'x' in load_state(env.settings).hosts


def test_remove_clears_pending(env, resets):
    env.probes.is_up = lambda ip: ip == X_IP
    with pytest.raises(GoadError):
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    extension_ops.remove(env.settings, env.runner, 'a', yes=True, ask=lambda q, y: True)
    assert load_state(env.settings).pending_extension is None


def test_remove_requires_ask():
    import inspect
    assert inspect.signature(extension_ops.remove).parameters['ask'].default is inspect.Parameter.empty


def test_remove_refuses_when_a_survivor_lacks_the_snapshot(env, installed, resets):
    env.runner._responses.insert(0, (lambda a: a[3] == 'listSnapshots' and 'srv02' in a[4],
                                     Result(0, 'Total snapshots: 1\next-a\n', '')))
    asked = []
    with pytest.raises(GoadError) as e:
        extension_ops.remove(env.settings, env.runner, 'a', yes=True, ask=lambda q, y: asked.append(q) or True)
    assert str(e.value) == 'snapshot base is missing on srv02: nothing was changed'
    assert asked == [] and resets == []
    assert not [a for a in env.runner.calls if a[3] in ('deleteVM', 'stop')]
    assert 'x' in load_state(env.settings).hosts


def test_remove_half_added_names_only_cloned_vms(env, catdir, resets):
    _write_ext(catdir, 'two', {'hosts': {'x': X, 'y': dict(X, hostname='yhost', octet=41)}})
    env.probes.is_up = lambda ip: ip == '192.168.56.41'
    with pytest.raises(GoadError, match='already answers'):
        extension_ops.add(env.settings, env.runner, env.store, 'two', probes=env.probes)
    assert 'x' not in load_state(env.settings).hosts   # refused before any host was added
    asked = []
    extension_ops.remove(env.settings, env.runner, 'two', yes=True, ask=lambda q, y: asked.append(q) or True)
    assert asked == ['Reset the lab to snapshot base? Changes made inside the VMs since base are lost.']
    assert not [a for a in env.runner.calls if a[3] in ('deleteVM', 'clone')]


def test_add_open_failure_says_resume(env, monkeypatch):
    def broken(*a, **k):
        raise GoadError('lab.yml: invalid YAML')
    monkeypatch.setattr('goad.lab.context.open_lab', broken)
    with pytest.raises(GoadError) as e:
        extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert str(e.value) == 'lab.yml: invalid YAML: run goad extension add a again to resume'
    assert load_state(env.settings).pending_extension == 'a'


def test_remove_refuses_scenario_requiring_extension(monkeypatch):
    needs = Scenario('needs', '', 'server', {}, requires='novm')
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: dict(CATALOGUE, needs=needs))
    raw = yaml.safe_load(text_with('novm'))
    raw['scenarios'] = [{'name': 'needs', 'target': 'srv02'}]
    with pytest.raises(GoadError, match=r'disable needs@srv02 first'):
        extension_ops.remove_entry(yaml.safe_dump(raw, sort_keys=False), 'novm')


def test_remove_expands_service_scenario_from_other_extension(env, resets, monkeypatch):
    monkeypatch.setattr('goad.lab.provision.provision', env.probes.provision)
    _write_ext(extensions.EXTENSION_DIR, 'svc', {'hosts': {'srv02': {'services': {'mssql': {}}}}})
    svcscn = Scenario('svcscn', '', 'service:mssql',
                      {'hosts': {'{target}': {'settings': {'smb.signing': 'optional'}}}}, requires='svc')
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: dict(CATALOGUE, svcscn=svcscn))
    old = text_with('svc', scenario_entries=[('svcscn', 'srv02')])
    text = text_with('svc', 'novm', scenario_entries=[('svcscn', 'srv02')])
    working_lab_path(env.settings).write_text(text)
    state = load_state(env.settings)
    state.snapshots.append(SnapshotRecord('ext-svc', '2026-11-24T00:00:00Z', 'ext-svc', old))
    save_state(env.settings, state)
    env.runner._responses.insert(0, (lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 1\next-svc\n', '')))
    assert extension_ops.remove(env.settings, env.runner, 'novm', yes=True, ask=lambda q, y: True) == 'ext-svc'


def test_add_saves_pending_before_writing_lab_yml(env, monkeypatch):
    seen = []
    real = extension_ops.save_state

    def save(settings, state):
        seen.append((state.pending_extension, 'extensions' in yaml.safe_load(working_lab_path(settings).read_text())))
        real(settings, state)
    monkeypatch.setattr(extension_ops, 'save_state', save)
    extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert seen[0] == ('a', False)


def test_add_resumes_when_pending_saved_but_lab_yml_not_written(env):
    state = load_state(env.settings)
    state.pending_extension = 'a'
    save_state(env.settings, state)
    record = extension_ops.add(env.settings, env.runner, env.store, 'a', probes=env.probes)
    assert record.name == 'ext-a' and [c[-1] for c in clones(env)] == ['-cloneName=2domains-x']
    assert yaml.safe_load(working_lab_path(env.settings).read_text())['extensions'] == ['a']
    assert load_state(env.settings).pending_extension is None


def test_remove_failed_reset_says_remove_again_and_recovers(env, installed, resets, monkeypatch):
    from goad.lab import provision as provisioning

    failing = [True]

    def reset(lab, name, wait=None, current_text=None):
        if failing[0]:
            raise GoadError('revert to base failed on dc01')
        working_lab_path(lab.settings).write_text(lab.state.snapshot(name).lab_yml)
    monkeypatch.setattr('goad.lab.snapshots.reset', reset)
    with pytest.raises(GoadError) as e:
        extension_ops.remove(env.settings, env.runner, 'a', yes=True, ask=lambda q, y: True)
    assert str(e.value) == 'revert to base failed on dc01: run goad extension remove a again'
    state = load_state(env.settings)
    assert 'x' not in state.hosts and state.pending_extension == 'a'
    # lab.yml still lists the extension: provision points to the extension commands, not to a redeploy
    with pytest.raises(GoadError) as e:
        provisioning.check_compatible(extension_ops.parse_lab(installed, 'lab.yml'), state)
    assert 'goad extension remove a' in str(e.value) and 'redeploy' not in str(e.value)
    failing[0] = False
    assert extension_ops.remove(env.settings, env.runner, 'a', yes=True, ask=lambda q, y: True) == 'base'
    state = load_state(env.settings)
    assert state.pending_extension is None and [s.name for s in state.snapshots] == ['base']
    assert 'extensions' not in yaml.safe_load(working_lab_path(env.settings).read_text())


def test_remove_failed_held_snapshot_delete_still_replays(env, resets, monkeypatch):
    monkeypatch.setattr('goad.lab.provision.provision', env.probes.provision)
    text = text_with('novm', scenario_entries=[('srvset', 'srv02')])
    working_lab_path(env.settings).write_text(text)
    state = load_state(env.settings)
    state.snapshots.append(SnapshotRecord('ext-novm', '2026-11-24T00:00:00Z', 'ext-novm', text_with('novm')))
    save_state(env.settings, state)

    def broken(lab, name):
        raise GoadError(f'delete snapshot {name} failed')
    monkeypatch.setattr('goad.lab.snapshots.delete', broken)
    with pytest.raises(GoadError) as e:
        extension_ops.remove(env.settings, env.runner, 'novm', yes=True, ask=lambda q, y: True)
    assert 'goad snapshot delete' in str(e.value) and 'ext-novm' in str(e.value)
    assert [p[0] for p in env.provisions] == [scenario_ops.ENABLE_TAGS]
    assert 'extensions' not in yaml.safe_load(working_lab_path(env.settings).read_text())
    assert load_state(env.settings).pending_extension is None
