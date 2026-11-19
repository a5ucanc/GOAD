from types import SimpleNamespace

import pytest

from goad.extension_service import ExtensionService
from goad.scenario_resolver import EnabledScenario
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

    def provision(name, install=True):
        calls.append(("provision", name) if install else ("unprovision", name))
        return provision.ok.get(install, True)
    provision.ok = {}

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


class FakeScenarios:
    def __init__(self, calls, affected):
        self.calls = calls
        self.affected = affected
        self.disable_ok = True

    def affected_by_extension_removal(self, name):
        return list(self.affected)

    def disable_entries(self, entries):
        self.calls.append(("disable_entries", [e.key for e in entries]))
        return self.disable_ok


class FakeExtension:
    def __init__(self, uninstall):
        self.uninstall = uninstall

    def has_uninstall(self):
        return self.uninstall


class FakeLab:
    def __init__(self, uninstall=True):
        self.uninstall = uninstall

    def get_extension(self, name):
        return FakeExtension(self.uninstall)


class NoVmProvider(FakeProvider):
    def extension_vm_names(self, name, lab_name, ip_range):
        return []


AFFECTED = [EnabledScenario("relay", "dc02", "t"), EnabledScenario("mssql-sysadmin", "srv02", "t")]


@pytest.fixture
def mssql_env():
    calls = []
    inst = FakeInstance(calls)
    inst.extensions.append("mssql")
    prov = NoVmProvider(calls)
    answers = {"yes": True, "asked": []}

    def ask(prompt):
        answers["asked"].append(prompt)
        return answers["yes"]

    def provision(name, install=True):
        calls.append(("provision", name) if install else ("unprovision", name))
        return provision.ok
    provision.ok = True

    scenarios = FakeScenarios(calls, AFFECTED)
    svc = ExtensionService(inst, prov, provision, ask=ask, scenarios=scenarios, lab=FakeLab())
    return SimpleNamespace(svc=svc, calls=calls, answers=answers, inst=inst, scenarios=scenarios,
                           provision=provision)


def test_remove_asks_and_disables_scenarios(mssql_env):
    e = mssql_env
    assert e.svc.remove("mssql")
    assert e.answers["asked"] == [
        "Remove extension mssql and disable scenarios relay@dc02, mssql-sysadmin@srv02? (y/N)"]
    assert e.calls == [("disable_entries", ["relay@dc02", "mssql-sysadmin@srv02"]),
                       ("unprovision", "mssql"), ("disable_extension", "mssql")]
    assert e.inst.extensions == []


def test_remove_declined_keeps_everything(mssql_env):
    e = mssql_env
    e.answers["yes"] = False
    assert not e.svc.remove("mssql")
    assert e.calls == []
    assert e.inst.extensions == ["mssql"]


def test_remove_no_tty_without_yes_refused(mssql_env):
    e = mssql_env
    e.svc.ask = None
    assert not e.svc.remove("mssql")
    assert e.calls == []
    assert e.inst.extensions == ["mssql"]


def test_remove_yes_skips_prompt(mssql_env):
    e = mssql_env
    assert e.svc.remove("mssql", yes=True)
    assert e.answers["asked"] == []
    assert ("disable_entries", ["relay@dc02", "mssql-sysadmin@srv02"]) in e.calls
    assert ("unprovision", "mssql") in e.calls


def test_remove_without_affected_uses_plain_prompt(mssql_env):
    e = mssql_env
    e.scenarios.affected = []
    assert e.svc.remove("mssql")
    assert e.answers["asked"] == ["Remove extension mssql without revert? (y/N)"]
    assert e.calls[0] == ("disable_entries", [])


def test_remove_scenario_failure_keeps_extension(mssql_env):
    e = mssql_env
    e.scenarios.disable_ok = False
    assert not e.svc.remove("mssql", yes=True)
    assert ("unprovision", "mssql") not in e.calls
    assert e.inst.extensions == ["mssql"]


def test_remove_uninstall_failure_keeps_extension(mssql_env):
    e = mssql_env
    e.provision.ok = False
    assert not e.svc.remove("mssql", yes=True)
    assert ("disable_extension", "mssql") not in e.calls
    assert not any(c[0] == "destroy" for c in e.calls)
    assert e.inst.extensions == ["mssql"]


def test_remove_without_uninstall_playbook_skips_provision(env):
    svc, calls, answers, snaps, inst, _ = env
    inst.extensions.append("ws01")
    svc.lab = FakeLab(uninstall=False)
    assert svc.remove("ws01", yes=True)
    assert not any(c[0] == "unprovision" for c in calls)
    assert ("destroy", ["GOAD-Base-WS01"]) in calls


def test_remove_runs_uninstall_before_destroy(env):
    svc, calls, answers, snaps, inst, _ = env
    inst.extensions.append("ws01")
    svc.lab = FakeLab(uninstall=True)
    assert svc.remove("ws01", yes=True)
    assert calls.index(("unprovision", "ws01")) < calls.index(("destroy", ["GOAD-Base-WS01"]))


def test_install_without_vms_skips_vagrant_up(mssql_env):
    e = mssql_env
    e.inst.extensions.clear()
    assert e.svc.install("mssql")
    assert ("up",) not in e.calls
    assert e.calls == [("enable_extension", "mssql"), ("provision", "mssql")]
