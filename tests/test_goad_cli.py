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
