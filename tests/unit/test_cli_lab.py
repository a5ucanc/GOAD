import contextlib
import re

import pytest
import yaml

from goad import GoadError
from goad.cli import Context, main
from goad.host.runner import Result
from goad.lab import deploy as deploy_module
from goad.lab import provision as provision_module
from goad.lab.deploy import Probes, step_firstboot
from goad.state import load_state, save_state, state_path, templates_in_use, working_lab_path


@pytest.fixture
def cli(monkeypatch, settings, fake):
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    return fake


def flat(text):
    return re.sub(r'\s+', ' ', text)


def test_lab_start_starts_off_vms_then_waits(cli, lab, monkeypatch):
    running = lab.vms()['dc01']
    cli.respond(lambda a: a[3] == 'list', Result(0, f'Total running VMs: 1\n{running}\n', ''))
    waited = []
    monkeypatch.setattr('goad.lab.power.wait_port', lambda ip, port, timeout: waited.append((ip, port)))
    # wait_ready binds wait=wait_port at def time: patch the default too
    monkeypatch.setattr('goad.lab.power.wait_ready.__defaults__', (900, lambda ip, port, timeout: waited.append((ip, port))))
    assert main(['lab', 'start']) == 0
    started = sorted(a[4] for a in cli.calls if a[3] == 'start')
    assert started == sorted(v for k, v in lab.vms().items() if k != 'dc01')
    assert sorted(waited) == sorted(lab.endpoints().values())


def add_snap(settings, deployed):
    from goad.state import SnapshotRecord
    deployed.snapshots.append(SnapshotRecord('pre', '2026-11-21T01:00:00Z', '', 'x'))
    save_state(settings, deployed)


def test_snapshot_delete_needs_yes(cli, settings, deployed, monkeypatch, capsys):
    add_snap(settings, deployed)
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert main(['snapshot', 'delete', 'pre']) == 2
    assert 'confirmation needed' in capsys.readouterr().err
    assert not any(a[3] == 'deleteSnapshot' for a in cli.calls)
    assert [s.name for s in load_state(settings).snapshots] == ['base', 'pre']


def test_snapshot_delete_yes(cli, settings, deployed, monkeypatch):
    add_snap(settings, deployed)
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    cli.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\npre\n', ''))
    assert main(['snapshot', 'delete', 'pre', '--yes']) == 0
    assert any(a[3] == 'deleteSnapshot' for a in cli.calls)
    assert load_state(settings).snapshot('pre') is None
    assert load_state(settings).snapshot('base') is not None


def test_lab_deploy_passes_range(cli, monkeypatch):
    seen = {}
    monkeypatch.setattr('goad.lab.deploy.deploy', lambda lab, settings, runner, store, ip_range=None, probes=None:
                        seen.update(lab=lab, ip_range=ip_range))
    monkeypatch.setattr('goad.host.awake.keep_host_awake', contextlib.nullcontext)
    assert main(['lab', 'deploy', '2domains', '--range', '10.9.8']) == 0
    assert seen == {'lab': '2domains', 'ip_range': '10.9.8'}


def edit_working(settings, edit):
    path = working_lab_path(settings)
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data))


@pytest.mark.parametrize('edit, words', [
    (lambda d: d['hosts']['srv02'].update(octet=d['hosts']['dc01']['octet']), ('duplicate octet',)),
    (lambda d: d['hosts']['srv02'].update(hostname='a' * 16), ('invalid Windows hostname', 'srv02')),
])
def test_provision_invalid_working_lab(cli, settings, deployed, monkeypatch, tmp_path, capsys, edit, words):
    playbook = tmp_path / 'site.yml'
    playbook.write_text('[]')
    monkeypatch.setattr(provision_module, 'PLAYBOOK', playbook)
    edit_working(settings, edit)
    assert main(['lab', 'provision']) == 1
    err = flat(capsys.readouterr().err)
    for word in words:
        assert word in err
    assert cli.calls == []


def test_provision_incompatible_edit(cli, settings, deployed, monkeypatch, tmp_path, capsys):
    playbook = tmp_path / 'site.yml'
    playbook.write_text('[]')
    monkeypatch.setattr(provision_module, 'PLAYBOOK', playbook)
    real = provision_module.provision
    monkeypatch.setattr(provision_module, 'provision', lambda *a, **k: real(*a, playbook=playbook, **k))
    monkeypatch.setattr('goad.host.awake.keep_host_awake', contextlib.nullcontext)
    edit_working(settings, lambda d: d['hosts']['srv02'].update(octet=30))
    assert main(['lab', 'provision']) == 1
    err = flat(capsys.readouterr().err)
    assert 'host srv02' in err and 'ip changed' in err
    assert not any(a[0].endswith('ansible-playbook') for a in cli.calls)


def test_templates_in_use_corrupt_state(settings):
    path = state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{not json')
    with pytest.raises(GoadError):
        templates_in_use(settings)


def test_lab_status_header(cli, deployed, capsys):
    assert main(['lab', 'status']) == 0
    assert 'lab 2domains (192.168.56.0/24), snapshot base, deploy step finish' in flat(capsys.readouterr().out)


def test_lab_status_header_dashes(cli, settings, deployed, capsys):
    deployed.current = None
    deployed.step = ''
    save_state(settings, deployed)
    assert main(['lab', 'status']) == 0
    assert 'snapshot -, deploy step -' in flat(capsys.readouterr().out)


def test_creds_prints_domain_admin_rows(cli, deployed, capsys):
    assert main(['creds']) == 0
    out = capsys.readouterr().out
    assert out.count('Administrator') >= 2
    assert 'SEVENKINGDOMS\\Administrator' in out and 'NORTH\\Administrator' in out
    assert 'domain sevenkingdoms.local' in out and 'Aa1234567890!' in out


def test_firstboot_linux_host_uses_ssh(lab):
    for name, host in lab.state.hosts.items():
        host.ready = name != 'srv02'
    lab.state.hosts['srv02'].template = 'ubuntu2404-v1'
    calls = []
    probes = Probes(wait_port=lambda ip, port, timeout: calls.append(('port', ip, port)),
                    check_psrp=lambda *a: calls.append(('psrp',) + a),
                    check_ssh=lambda ip: calls.append(('ssh', ip)),
                    remove_setup_account=lambda ip, pw: calls.append(('remove', ip)),
                    firstboot_marker=lambda *a: 'done')
    step_firstboot(lab, probes)
    ip = lab.state.hosts['srv02'].ip
    assert ('port', ip, 22) in calls and ('ssh', ip) in calls
    assert not any(c[0] in ('psrp', 'remove', 'firstboot') for c in calls)
    assert lab.state.hosts['srv02'].ready


def test_provision_prints_elapsed(cli, deployed, monkeypatch, tmp_path, capsys):
    playbook = tmp_path / 'site.yml'
    playbook.write_text('[]')
    monkeypatch.setattr(provision_module, 'PLAYBOOK', playbook)
    monkeypatch.setattr(provision_module, 'provision', lambda *a, **k: True)
    assert main(['lab', 'provision']) == 0
    assert re.search(r'provisioned in \d+ s', capsys.readouterr().out)


def test_scenario_disable_needs_yes(cli, settings, deployed, monkeypatch, capsys):
    from goad.lab import scenarios
    from goad.lab.scenarios import Scenario
    frag = {'domains': {'{domain}': {'users': {'scn.user': {'firstname': 'S', 'surname': 'U'}}}}}
    monkeypatch.setattr(scenarios, 'load_catalogue', lambda *a, **k: {'newuser': Scenario('newuser', '', 'domain', frag)})
    raw = yaml.safe_load(working_lab_path(settings).read_text())
    raw['scenarios'] = [{'name': 'newuser', 'target': 'dc02'}]
    text = yaml.safe_dump(raw, sort_keys=False)
    working_lab_path(settings).write_text(text)
    resets = []
    monkeypatch.setattr('goad.lab.snapshots.reset', lambda *a, **k: resets.append(a))
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert main(['scenario', 'disable', 'newuser']) == 2
    assert 'confirmation needed' in capsys.readouterr().err
    assert resets == [] and working_lab_path(settings).read_text() == text


def test_snapshot_list_shows_scenarios(cli, settings, deployed, capsys, monkeypatch):
    monkeypatch.setenv('COLUMNS', '200')   # the extra Extensions column no longer fits 80
    from goad.state import SnapshotRecord
    deployed.snapshots.append(SnapshotRecord('pre', '2026-11-21T01:00:00Z', '',
                                             'scenarios:\n- {name: esc1, target: dc01}\n- {name: kerb, target: dc02}\n'))
    save_state(settings, deployed)
    cli.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\npre\n', ''))
    assert main(['snapshot', 'list']) == 0
    out = flat(capsys.readouterr().out)
    assert 'Scenarios' in out and 'esc1@dc01, kerb@dc02' in out


def test_snapshot_list_marks_unusable(cli, settings, deployed, capsys, monkeypatch):
    monkeypatch.setenv('COLUMNS', '200')
    from goad.state import SnapshotRecord, working_lab_path
    path = working_lab_path(settings)
    path.write_text(path.read_text() + 'extensions: [mssql]\n')
    deployed.snapshots.append(SnapshotRecord('pre', '2026-11-21T01:00:00Z', '', path.read_text()))
    save_state(settings, deployed)
    cli.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\npre\n', ''))
    assert main(['snapshot', 'list']) == 0
    out = flat(capsys.readouterr().out)
    assert 'Extensions' in out and 'base (unusable)' in out and 'pre (unusable)' not in out


@pytest.fixture
def ext_catalogue(monkeypatch, tmp_path):
    from goad.lab import extensions
    directory = tmp_path / 'extensions'
    directory.mkdir()
    (directory / 'a.yml').write_text('description: ext a\nlabs:\n  2domains: {}\n')
    (directory / 'elk.yml').write_text(
        'description: elk\nlabs:\n  2domains: {}\ncredentials:\n'
        '  - {account: elastic, password: "Aa1234567890!", scope: "elk (http://{range}.50:5601)"}\n')
    monkeypatch.setattr(extensions, 'EXTENSION_DIR', directory)
    return directory


def test_extension_list_without_lab(cli, settings, ext_catalogue, capsys, monkeypatch):
    monkeypatch.setenv('COLUMNS', '200')
    assert main(['extension', 'list']) == 0
    out = capsys.readouterr().out
    assert 'a' in out and 'ext a' in out and 'elk' in out


def test_extension_list_marks_applies_and_installed(cli, settings, deployed, ext_catalogue, capsys, monkeypatch):
    monkeypatch.setenv('COLUMNS', '200')
    path = working_lab_path(settings)
    path.write_text(path.read_text() + 'extensions: [a]\n')
    assert main(['extension', 'list']) == 0
    rows = {line.split()[1]: [t for t in line.split() if t != '│'] for line in capsys.readouterr().out.splitlines() if line.startswith('│ ')}
    assert rows['a'][-2:] == ['yes', 'yes']
    assert rows['elk'][-2:] == ['yes', 'no']


def test_extension_add(cli, settings, deployed, ext_catalogue, monkeypatch, capsys):
    from goad.lab import extension_ops
    from goad.state import SnapshotRecord
    calls = []
    monkeypatch.setattr(extension_ops, 'add', lambda s, r, store, name: calls.append(name) or SnapshotRecord('ext-a', '', '', ''))
    monkeypatch.setattr('goad.cli._store', lambda ctx: None)
    assert main(['extension', 'add', 'a']) == 0
    assert calls == ['a']
    assert 'extension a added (snapshot ext-a)' in capsys.readouterr().out


def test_extension_remove(cli, settings, deployed, ext_catalogue, monkeypatch, capsys):
    from goad.lab import extension_ops
    path = working_lab_path(settings)
    path.write_text(path.read_text() + 'extensions: [a]\n')
    seen = []
    monkeypatch.setattr(extension_ops, 'remove', lambda s, r, name, yes, ask: seen.append((name, yes)) or 'base')
    assert main(['extension', 'remove', 'a', '--yes']) == 0
    assert seen == [('a', True)]
    assert 'extension a removed (lab reset to base)' in flat(capsys.readouterr().out)


def test_extension_remove_validates_before_prompt(cli, settings, deployed, ext_catalogue, monkeypatch, capsys):
    from goad.lab import extension_ops
    monkeypatch.setattr(extension_ops, 'remove', lambda *a, **k: pytest.fail('must validate first'))
    assert main(['extension', 'remove', 'a']) == 1
    assert 'extension a is not installed' in capsys.readouterr().err
