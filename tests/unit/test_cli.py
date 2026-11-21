import pytest

from goad import GoadError
from goad.cli import HANDLERS, Context, NeedsConfirmation, build_parser, confirm, main


def test_help_lists_groups(capsys):
    with pytest.raises(SystemExit) as e:
        main(['--help'])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert 'check' in out and 'template' in out


def test_confirm_non_tty_without_yes_raises(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(NeedsConfirmation):
        confirm('Delete?', yes=False)


def test_confirm_yes_flag_skips_prompt(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert confirm('Delete?', yes=True) is True


def test_confirm_tty_reads_answer(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt: 'y')
    assert confirm('Delete?', yes=False) is True


def test_needs_confirmation_exit_code(monkeypatch, capsys):
    def handler(args, ctx):
        raise NeedsConfirmation('Delete template win2025-v1?')
    monkeypatch.setattr('goad.cli.HANDLERS', {('check',): handler})
    monkeypatch.setattr('goad.cli.make_context', lambda: None)
    assert main(['check']) == 2
    assert '--yes' in capsys.readouterr().err


def test_goad_error_exit_code(monkeypatch, capsys):
    def handler(args, ctx):
        raise GoadError('boom')
    monkeypatch.setattr('goad.cli.HANDLERS', {('check',): handler})
    monkeypatch.setattr('goad.cli.make_context', lambda: None)
    assert main(['check']) == 1
    assert 'boom' in capsys.readouterr().err


def test_unknown_command_exit_code():
    with pytest.raises(SystemExit) as e:
        main(['nope'])
    assert e.value.code == 2


@pytest.mark.parametrize('argv, command', [
    (['lab', 'deploy', '2domains'], ('lab', 'deploy')),
    (['lab', 'reset'], ('lab', 'reset')),
    (['snapshot', 'take', 'pre-adcs'], ('snapshot', 'take')),
    (['vm', 'console', 'dc01'], ('vm', 'console')),
    (['creds'], ('creds',)),
])
def test_parser_routes(argv, command):
    args = build_parser().parse_args(argv)
    assert args.command == command and command in HANDLERS


def test_reset_defaults_to_base():
    assert build_parser().parse_args(['lab', 'reset']).snapshot == 'base'


def test_bad_range_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(['lab', 'deploy', '2domains', '--range', '192.168.56.0/24'])


def test_no_lab_exit_code(monkeypatch, settings, fake, capsys):
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    assert main(['lab', 'status']) == 1
    assert 'no lab deployed' in capsys.readouterr().err


def test_provision_without_playbook(monkeypatch, settings, fake, deployed, tmp_path, capsys):
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    monkeypatch.setattr('goad.lab.provision.PLAYBOOK', tmp_path / 'missing.yml')
    assert main(['lab', 'provision']) == 1
    assert 'no Ansible playbooks yet (ansible/site.yml)' in capsys.readouterr().err


def test_reset_unknown_snapshot(monkeypatch, settings, fake, deployed, capsys):
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    assert main(['lab', 'reset', 'nope']) == 1
    assert 'unknown snapshot nope' in capsys.readouterr().err


def test_reset_ignores_corrupt_working_lab(monkeypatch, settings, fake, deployed):
    from goad.state import working_lab_path
    working_lab_path(settings).write_text('not: [valid')
    seen = []
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    monkeypatch.setattr('goad.lab.snapshots.reset', lambda lab, name: seen.append((lab, name)) or 0.0)
    assert main(['lab', 'reset']) == 0
    lab, name = seen[0]
    assert name == 'base' and lab.definition.name == '2domains'


@pytest.mark.parametrize('argv', [['lab', 'status'], ['lab', 'stop'], ['snapshot', 'list'],
                                  ['vm', 'stop', 'dc01'], ['vm', 'start', 'dc01']])
def test_corrupt_working_lab_does_not_block(monkeypatch, settings, fake, deployed, argv):
    from goad.state import working_lab_path
    working_lab_path(settings).write_text('not: [valid')
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    assert main(argv) == 0


@pytest.mark.parametrize('argv', [['creds'], ['snapshot', 'take', 'x']])
def test_corrupt_working_lab_refused_where_needed(monkeypatch, settings, fake, deployed, argv, capsys):
    from goad.state import working_lab_path
    working_lab_path(settings).write_text('not: [valid')
    monkeypatch.setattr('goad.cli.make_context', lambda: Context(settings, fake))
    assert main(argv) == 1
    assert 'invalid YAML' in capsys.readouterr().err
    assert fake.calls == []
