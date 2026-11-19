from pathlib import Path

import pytest

from goad.provider.provider import Provider
from goad.provider.vagrant.virtualbox import VirtualboxProvider
from goad.provider.vagrant.vmware import VmwareProvider
from goad.vagrant_names import vm_names_in

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vagrant_snapshot_list.txt"


class FakeCommand:
    def __init__(self, results=None, output=""):
        self.calls = []
        self.results = list(results or [])
        self.output = output

    def run_vagrant(self, args, path):
        self.calls.append(args)
        return self.results.pop(0) if self.results else True

    def run_vagrant_output(self, args, path):
        self.calls.append(args)
        return True, self.output


@pytest.fixture
def provider():
    p = VmwareProvider("GOAD-Base")
    p.path = "/tmp/nowhere"
    p.command = FakeCommand()
    return p


def test_snapshot_list_parses_fixture(provider):
    provider.command.output = FIXTURE.read_text()
    assert provider.snapshot_list() == {
        "GOAD-Base-DC01": ["probe-a", "probe-b"], "GOAD-Base-DC02": [], "GOAD-Base-DC03": [],
        "GOAD-Base-SRV02": [], "GOAD-Base-SRV03": []}
    assert provider.command.calls == [["snapshot", "list", "--machine-readable"]]


def test_snapshot_save_args(provider):
    assert provider.snapshot_save("scn-01-x@h")
    assert provider.command.calls == [["snapshot", "save", "scn-01-x@h"]]


def test_snapshot_restore_per_vm_no_provision(provider):
    assert provider.snapshot_restore("s", ["A", "B"])
    assert provider.command.calls == [["snapshot", "restore", "--no-provision", "A", "s"],
                                      ["snapshot", "restore", "--no-provision", "B", "s"]]


def test_snapshot_restore_stops_at_first_failure(provider):
    provider.command.results = [False]
    assert not provider.snapshot_restore("s", ["A", "B"])
    assert len(provider.command.calls) == 1


def test_snapshot_delete_per_vm(provider):
    assert provider.snapshot_delete("s", ["A", "B"])
    assert provider.command.calls == [["snapshot", "delete", "A", "s"], ["snapshot", "delete", "B", "s"]]


def test_destroy_vms_force(provider):
    assert provider.destroy_vms(["A"])
    assert provider.command.calls == [["destroy", "-f", "A"]]


def test_vm_names_from_generated_vagrantfile(provider, tmp_path):
    (tmp_path / "Vagrantfile").write_text('boxes = [\n { :name => "GOAD-Base-DC01", :ip => "x" },\n'
                                          '  { :name   =>  "GOAD-Base-SRV02" }]\n')
    provider.path = str(tmp_path)
    assert provider.vm_names() == ["GOAD-Base-DC01", "GOAD-Base-SRV02"]


def test_vm_names_in_extension_vagrantfile(provider):
    assert provider.extension_vm_names("guacamole", "GOAD-Base", "192.168.56") == ["GOAD-Base-GUACAMOLE"]


def test_vm_names_in_ignores_other_keys():
    assert vm_names_in(':box => "x", :name => "A"') == ["A"]


def test_only_vmware_supports_named_snapshots():
    assert VmwareProvider("x").supports_named_snapshots()
    assert not VirtualboxProvider("x").supports_named_snapshots()
    assert not Provider("x").supports_named_snapshots()
