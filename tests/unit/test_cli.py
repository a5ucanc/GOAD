import pytest

from goad import GoadError
from goad.cli import NeedsConfirmation, confirm, main


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
