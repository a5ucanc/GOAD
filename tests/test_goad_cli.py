import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("goad_cli", str(ROOT / "goad.py"))
goad_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(goad_cli)


class FakeProvisioner:
    use_jumpbox = False

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def run_disable_vagrant(self, disable_vagrant=True):
        self.calls.append(("disable_vagrant", disable_vagrant))
        return self.result

    def run_extension(self, extension, extensions, install=True, use_disable_vagrant_inventory=False):
        self.calls.append(("run_extension", extension, use_disable_vagrant_inventory))
        return self.result


def make_cli(is_base=True, vagrant_disabled=False, result=True):
    instance = SimpleNamespace(extensions=["elk"], vagrant_disabled=vagrant_disabled)
    instance.set_vagrant_disabled = lambda value: setattr(instance, "vagrant_disabled", value)
    lab = SimpleNamespace(is_base=lambda: is_base, get_extension=lambda name: name)
    provisioner = FakeProvisioner(result)
    cli = goad_cli.Goad.__new__(goad_cli.Goad)
    cli.lab_manager = SimpleNamespace(
        get_current_instance=lambda: instance,
        get_current_instance_lab=lambda: lab,
        get_current_instance_provisioner=lambda: provisioner,
    )
    return cli, instance, provisioner


@pytest.mark.parametrize("result", [True, False])
def test_disable_enable_vagrant_update_flag(result):
    cli, instance, _ = make_cli(result=result)
    cli.do_disable_vagrant("")
    assert instance.vagrant_disabled is result
    instance.vagrant_disabled = True
    cli.do_enable_vagrant("")
    assert instance.vagrant_disabled is (not result)


@pytest.mark.parametrize("is_base,vagrant_disabled,expected", [
    (True, True, True),
    (True, False, False),
    (False, True, False),
])
def test_provision_extension_inventory_choice(is_base, vagrant_disabled, expected):
    cli, _, provisioner = make_cli(is_base=is_base, vagrant_disabled=vagrant_disabled)
    cli.do_provision_extension("elk")
    assert provisioner.calls == [("run_extension", "elk", expected)]


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return True
        return method


def services_cli(monkeypatch, tty):
    cli, _, _ = make_cli()
    monkeypatch.setattr(goad_cli.sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("input() reached"))
    seen = {}

    def scenario_service(ask=None):
        seen["ask"] = ask
        seen["svc"] = Recorder()
        return seen["svc"]

    def extension_service(ask=None):
        seen["ask"] = ask
        seen["svc"] = Recorder()
        return seen["svc"]

    cli._scenario_service = scenario_service
    cli._extension_service = extension_service
    return cli, seen


@pytest.mark.parametrize("command,arg", [
    ("do_enable_scenario", "esc8"), ("do_disable_scenario", "esc8 dc01"),
    ("do_install_extension", "elk"), ("do_remove_extension", "elk"),
])
def test_no_tty_never_prompts(monkeypatch, command, arg):
    cli, seen = services_cli(monkeypatch, tty=False)
    getattr(cli, command)(arg)
    assert seen["ask"] is None


@pytest.mark.parametrize("command,arg", [
    ("do_enable_scenario", "esc8 --no-snapshot"), ("do_disable_scenario", "--no-snapshot esc8"),
    ("do_install_extension", "elk --no-snapshot"),
])
def test_no_snapshot_flag_disables_ask(monkeypatch, command, arg):
    cli, seen = services_cli(monkeypatch, tty=True)
    getattr(cli, command)(arg)
    assert seen["ask"] is None


def test_tty_gives_an_ask(monkeypatch):
    cli, seen = services_cli(monkeypatch, tty=True)
    cli.do_enable_scenario("esc8")
    assert seen["ask"] is not None
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert seen["ask"]("Q? (y/N)") is True


def test_remove_extension_flags(monkeypatch):
    cli, seen = services_cli(monkeypatch, tty=False)
    cli.do_remove_extension("--yes elk")
    assert seen["svc"].calls == [("remove", ("elk",), {"yes": True})]
    cli.do_remove_extension("elk")
    assert seen["svc"].calls == [("remove", ("elk",), {"yes": False})]


def test_flags_are_stripped_from_positional_args(monkeypatch):
    cli, seen = services_cli(monkeypatch, tty=True)
    cli.do_disable_scenario("esc8 dc01 --cascade --no-snapshot")
    assert seen["svc"].calls == [("disable", ("esc8", "dc01"), {"cascade": True})]
    cli.do_enable_scenario("--no-snapshot esc8 dc01")
    assert seen["svc"].calls == [("enable", ("esc8", "dc01"), {})]
    cli.do_install_extension("--no-snapshot elk")
    assert seen["svc"].calls == [("install", ("elk",), {})]


def test_lab_install_installs_extensions_without_prompt():
    source = (ROOT / "goad.py").read_text()
    calls = [line.strip() for line in source.splitlines() if "self.do_install_extension(" in line]
    assert calls and all("--no-snapshot" in call for call in calls)


def test_list_snapshots_prints_rows(monkeypatch, capsys):
    cli, _, _ = make_cli()
    fake = SimpleNamespace(supported=lambda: True,
                           rows=lambda: [("scn-01-maq@dc02", "maq@dc02", "", "", "5/5")])
    cli._lab_snapshots = lambda: fake
    cli.do_list_snapshots("")
    out = capsys.readouterr().out
    assert "scn-01-maq@dc02" in out and "5/5" in out


def test_list_snapshots_unsupported_provider(monkeypatch, capsys):
    cli, _, _ = make_cli()
    cli._lab_snapshots = lambda: SimpleNamespace(supported=lambda: False)
    cli.do_list_snapshots("")
    assert "scn-" not in capsys.readouterr().out
