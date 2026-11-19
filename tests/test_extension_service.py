import pytest

from goad.extension_service import ExtensionService
from tests.test_scenario_service import FakeSnapshots


class FakeInstance:
    lab_name = "GOAD-Base"
    ip_range = "192.168.56"

    def __init__(self, calls):
        self.extensions = []
        self.calls = calls

    def enable_extension(self, name):
        self.calls.append(("enable_extension", name))
        self.extensions.append(name)

    def disable_extension(self, name):
        self.calls.append(("disable_extension", name))
        self.extensions.remove(name)


class FakeProvider:
    def __init__(self, calls):
        self.calls = calls
        self.destroy_ok = True

    def install(self):
        self.calls.append(("up",))
        return True

    def extension_vm_names(self, name, lab_name, ip_range):
        return [f"{lab_name}-{name.upper()}"]

    def destroy_vms(self, vms):
        self.calls.append(("destroy", vms))
        return self.destroy_ok


class Snaps(FakeSnapshots):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls


@pytest.fixture
def env():
    calls = []
    inst = FakeInstance(calls)
    prov = FakeProvider(calls)
    snaps = Snaps(calls)
    answers = {"yes": True, "asked": []}

    def ask(prompt):
        answers["asked"].append(prompt)
        return answers["yes"]

    def provision(name):
        calls.append(("provision", name))
        return True

    svc = ExtensionService(inst, prov, provision, snapshots=snaps, ask=ask)
    return svc, calls, answers, snaps, inst, prov


def test_install_snapshot_then_up_then_provision(env):
    svc, calls, answers, *_ = env
    assert svc.install("ws01")
    assert answers["asked"] == ["Take a lab snapshot before installing extension ws01? (y/N)"]
    assert calls == [("take", "extension:ws01"), ("enable_extension", "ws01"), ("up",), ("provision", "ws01")]


def test_install_stops_when_snapshot_fails(env):
    svc, calls, _, snaps, inst, _ = env
    snaps.take_ok = False
    assert not svc.install("ws01")
    assert inst.extensions == []
    assert ("up",) not in calls


def test_remove_offers_revert(env):
    svc, calls, answers, snaps, inst, _ = env
    assert svc.install("ws01")
    assert svc.remove("ws01")
    assert answers["asked"][-1] == "Revert the lab to ext-01-ws01 instead of removing? (y/N)"
    assert ("revert", "ext-01-ws01") in calls
    assert ("destroy", ["GOAD-Base-WS01"]) not in calls


def test_remove_without_snapshot_destroys_vms_and_disables(env):
    svc, calls, answers, snaps, inst, _ = env
    answers["yes"] = False
    assert svc.install("ws01")
    answers["yes"] = True
    assert svc.remove("ws01")
    assert answers["asked"][-1] == "Remove extension ws01 without revert? (y/N)"
    assert calls.index(("destroy", ["GOAD-Base-WS01"])) < calls.index(("disable_extension", "ws01"))
    assert inst.extensions == []


def test_remove_destroys_before_disable(env):
    svc, calls, answers, snaps, inst, prov = env
    answers["yes"] = False
    assert svc.install("ws01")
    answers["yes"] = True
    prov.destroy_ok = False
    assert not svc.remove("ws01")
    assert inst.extensions == ["ws01"]
    assert ("disable_extension", "ws01") not in calls


def test_remove_declined_revert_then_confirmed_forgets_snapshot(env):
    svc, calls, answers, snaps, inst, _ = env
    assert svc.install("ws01")
    answers["yes"] = False
    svc.ask = lambda prompt: (answers["asked"].append(prompt), prompt.startswith("Remove"))[1]
    assert svc.remove("ws01")
    assert ("forget", "extension:ws01") in calls
    assert inst.extensions == []


def test_remove_declined_confirmation_does_nothing(env):
    svc, calls, answers, snaps, inst, _ = env
    answers["yes"] = False
    assert svc.install("ws01")
    assert not svc.remove("ws01")
    assert inst.extensions == ["ws01"]
    assert not any(c[0] == "destroy" for c in calls)


def test_remove_without_ask_needs_yes(env):
    svc, calls, answers, snaps, inst, _ = env
    svc.ask = None
    inst.extensions.append("ws01")
    assert not svc.remove("ws01")
    assert inst.extensions == ["ws01"]
    assert svc.remove("ws01", yes=True)
    assert inst.extensions == []


def test_remove_unknown_extension(env):
    svc, *_ = env
    assert not svc.remove("ws01")
