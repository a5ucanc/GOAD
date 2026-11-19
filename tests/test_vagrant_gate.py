from types import SimpleNamespace

import pytest

from goad.provider.vagrant.virtualbox import VirtualboxProvider
from goad.provider.vagrant.vmware import VmwareProvider
from goad.vagrant_gate import VagrantGate

VMS = ["GOAD-Base-DC01", "GOAD-Base-DC02"]
VMX = {vm: f"C:/Labs/GOAD/workspace/x/provider/.vagrant/machines/{vm}/vmware_desktop/u/{vm}.vmx" for vm in VMS}


class FakeCommand:
    def __init__(self, running=(), vmrun_ok=True, vagrant_ok=True):
        self.calls = []
        self.running = list(running)
        self.vmrun_ok = vmrun_ok
        self.vagrant_ok = vagrant_ok

    def run_vagrant(self, args, path):
        self.calls.append(("vagrant", args))
        return self.vagrant_ok

    def run_vmrun(self, args, path):
        self.calls.append(("vmrun", args))
        return self.vmrun_ok

    def run_vmrun_output(self, args, path):
        self.calls.append(("vmrun", args))
        # vmrun prints Windows paths with backslashes, the vagrant id file has forward slashes
        lines = [VMX[vm].replace("/", "\\") for vm in self.running]
        return True, f"Total running VMs: {len(lines)}\n" + "\n".join(lines) + "\n"


class FakeProvisioner:
    def __init__(self, command, enable_ok=True, disable_ok=True):
        self.command = command
        self.ok = {False: enable_ok, True: disable_ok}
        self.shutdown_works = True

    def run_disable_vagrant(self, disable_vagrant=True):
        self.command.calls.append(("ansible", "disable" if disable_vagrant else "enable"))
        return self.ok[disable_vagrant]

    def run_shutdown(self, hosts, extensions):
        self.command.calls.append(("ansible", "shutdown " + ",".join(hosts)))
        if self.shutdown_works:
            # the guests power off: vmrun list stops showing them
            self.command.running = [vm for vm in self.command.running if vm.split("-")[-1].lower() not in hosts]
        return True


def make_instance(disabled):
    instance = SimpleNamespace(vagrant_disabled=disabled)
    instance.set_vagrant_disabled = lambda value: setattr(instance, "vagrant_disabled", value)
    return instance


def setup(provider, disabled, **command_kwargs):
    provider.command = FakeCommand(**command_kwargs)
    instance = make_instance(disabled)
    instance.lab_name = "GOAD-Base"
    instance.extensions = []
    provisioner = FakeProvisioner(provider.command)
    provider.set_vagrant_gate(VagrantGate(instance, provider, provisioner))
    return instance, provisioner


@pytest.fixture
def provider():
    p = VmwareProvider("GOAD-Base")
    p.path = "/tmp/nowhere"
    p.vm_names = lambda: list(VMS)
    p._vmx = lambda vm: VMX.get(vm)
    return p


def kinds(command, *wanted):
    return [(kind, args) for kind, args in command.calls if kind in wanted]


def test_enabled_account_runs_vagrant_directly(provider):
    instance, _ = setup(provider, False, running=VMS)
    assert provider.start()
    assert provider.command.calls == [("vagrant", ["up"])]


def test_start_boots_enables_runs_then_disables_again(provider):
    instance, _ = setup(provider, True, running=["GOAD-Base-DC01"])
    assert provider.start()
    assert kinds(provider.command, "vagrant", "ansible") == [
        ("ansible", "enable"), ("vagrant", ["up"]), ("ansible", "disable")]
    starts = [args for kind, args in provider.command.calls if kind == "vmrun" and "start" in args]
    assert starts == [["-T", "ws", "start", VMX["GOAD-Base-DC02"], "nogui"]]
    assert instance.vagrant_disabled is True


@pytest.mark.parametrize("method,args,expected", [
    ("install", (), ["up"]),
    ("reset", (), ["snapshot", "pop", "--no-delete"]),
    ("start_vm", ("GOAD-Base-DC01",), ["up", "GOAD-Base-DC01"]),
])
def test_guest_login_commands_are_gated(provider, method, args, expected):
    instance, _ = setup(provider, True, running=VMS)
    assert getattr(provider, method)(*args)
    assert kinds(provider.command, "vagrant", "ansible") == [
        ("ansible", "enable"), ("vagrant", expected), ("ansible", "disable")]
    assert instance.vagrant_disabled is True


def test_failed_command_still_disables_again(provider):
    instance, _ = setup(provider, True, running=VMS, vagrant_ok=False)
    assert not provider.start()
    assert kinds(provider.command, "ansible") == [("ansible", "enable"), ("ansible", "disable")]
    assert instance.vagrant_disabled is True


def test_failed_redisable_keeps_flag_accurate(provider):
    instance, provisioner = setup(provider, True, running=VMS)
    provisioner.ok[True] = False
    assert provider.start()
    assert instance.vagrant_disabled is False


def test_failed_enable_blocks_vagrant(provider):
    instance, provisioner = setup(provider, True, running=VMS)
    provisioner.ok[False] = False
    assert not provider.start()
    assert instance.vagrant_disabled is True
    assert kinds(provider.command, "vagrant") == []


def test_failed_boot_blocks_vagrant(provider):
    instance, _ = setup(provider, True, running=[], vmrun_ok=False)
    assert not provider.start()
    assert kinds(provider.command, "vagrant", "ansible") == []


@pytest.mark.parametrize("method,args,stopped", [
    ("stop", (), VMS),
    ("stop_vm", ("GOAD-Base-DC02",), ["GOAD-Base-DC02"]),
])
def test_halt_with_disabled_account_shuts_down_from_the_guest(provider, method, args, stopped):
    instance, _ = setup(provider, True, running=VMS)
    assert getattr(provider, method)(*args)
    hosts = ",".join(vm.split("-")[-1].lower() for vm in stopped)
    assert kinds(provider.command, "vagrant", "ansible") == [("ansible", "shutdown " + hosts)]
    assert not [args for kind, args in provider.command.calls if kind == "vmrun" and "stop" in args]
    assert instance.vagrant_disabled is True


def test_halt_skips_vms_already_off(provider):
    setup(provider, True, running=["GOAD-Base-DC01"])
    assert provider.stop()
    assert kinds(provider.command, "ansible") == [("ansible", "shutdown dc01")]


def test_halt_with_lab_off_does_nothing(provider):
    setup(provider, True, running=[])
    assert provider.stop()
    assert kinds(provider.command, "vagrant", "ansible") == []


def test_halt_forces_off_vms_that_ignore_the_shutdown(provider, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    _, provisioner = setup(provider, True, running=["GOAD-Base-DC01"])
    provisioner.shutdown_works = False
    monkeypatch.setattr(provider, "wait_halted",
                        lambda vms, timeout=600, interval=10: type(provider).wait_halted(provider, vms, timeout=0))
    assert provider.stop()
    stops = [args for kind, args in provider.command.calls if kind == "vmrun" and "stop" in args]
    assert stops == [["-T", "ws", "stop", VMX["GOAD-Base-DC01"], "hard"]]


def test_halt_with_enabled_account_uses_vagrant(provider):
    setup(provider, False, running=VMS)
    assert provider.stop()
    assert provider.command.calls == [("vagrant", ["halt"])]


def test_halt_without_vmrun_enables_and_leaves_enabled():
    p = VirtualboxProvider("GOAD-Base")
    p.path = "/tmp/nowhere"
    p.vm_names = lambda: list(VMS)
    instance, _ = setup(p, True)
    assert p.stop()
    assert kinds(p.command, "vagrant", "ansible") == [("ansible", "enable"), ("vagrant", ["halt"])]
    assert instance.vagrant_disabled is False


def test_commands_without_guest_login_are_not_gated(provider):
    instance, _ = setup(provider, True, running=VMS)
    provider.status()
    provider.snapshot_save("snap-01")
    provider.destroy_vms(["GOAD-Base-DC02"])
    assert kinds(provider.command, "ansible") == []
    assert instance.vagrant_disabled is True


def test_running_vms_matches_vmrun_list(provider):
    provider.command = FakeCommand(running=["GOAD-Base-DC02"])
    assert provider.running_vms() == ["GOAD-Base-DC02"]
