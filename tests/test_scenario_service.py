import pytest

from goad.scenario import Scenarios
from goad.scenario_resolver import ScenarioResolver, EnabledScenario
from goad.scenario_service import ScenarioService


class FakeProvisioner:
    def __init__(self):
        self.calls = []
        self.fail_on = set()

    def run_scenario(self, scenario, target, extensions, install=True):
        self.calls.append((scenario.name, target, install))
        return (scenario.name, install) not in self.fail_on


class FakeInstance:
    extensions = []

    def __init__(self):
        self.scenarios = []

    def add_scenario(self, name, target):
        self.scenarios.append(EnabledScenario(name, target, "t"))

    def remove_scenario(self, name, target):
        self.scenarios = [s for s in self.scenarios if s.key != f"{name}@{target}"]

    def mark_scenario_dirty(self, name, target):
        for s in self.scenarios:
            if s.key == f"{name}@{target}":
                s.status = "dirty"


class FakeLab:
    def __init__(self, resolver):
        self.resolver = resolver

    def get_scenario_resolver(self):
        return self.resolver

    def get_scenario(self, name):
        return self.resolver.scenarios.get(name)


@pytest.fixture
def prov():
    return FakeProvisioner()


@pytest.fixture
def svc(scenario_dir, tmp_path, prov):
    scenario_dir.make("esc8", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    scenario_dir.make("relay", depends=["esc8"])
    scenario_dir.make("unknown-cap-scenario", requires=["nonexistent"])
    resolver = ScenarioResolver(Scenarios(str(tmp_path)), "GOAD-Base", {"adcs": ["dc01", "srv03"]}, "dc01", ["dc01"])
    return ScenarioService(FakeInstance(), FakeLab(resolver), prov)


def test_enable_records_state(svc, prov):
    assert svc.enable("esc8", None)
    assert prov.calls == [("esc8", "dc01", True)]
    assert [(e.name, e.target) for e in svc.instance.scenarios] == [("esc8", "dc01")]


def test_enable_refused_runs_nothing(svc, prov):
    assert not svc.enable("esc8", "srv02")
    assert prov.calls == []


def test_failed_install_cleans_up_and_records_nothing(svc, prov):
    prov.fail_on = {("esc8", True)}
    assert not svc.enable("esc8", None)
    assert prov.calls == [("esc8", "dc01", True), ("esc8", "dc01", False)]
    assert svc.instance.scenarios == []


def test_disable_requires_host_when_ambiguous(svc):
    svc.enable("esc8", "dc01")
    svc.enable("esc8", "srv03")
    assert not svc.disable("esc8", None)
    assert svc.disable("esc8", "srv03")


def test_disable_blocked_by_dependents_without_cascade(svc):
    svc.enable("esc8", None)
    svc.enable("relay", None)
    assert not svc.disable("esc8", None)


def test_cascade_disables_dependents_first(svc, prov):
    svc.enable("esc8", None)
    svc.enable("relay", None)
    prov.calls.clear()
    assert svc.disable("esc8", None, cascade=True)
    assert [c[0] for c in prov.calls] == ["relay", "esc8"]


def test_failed_uninstall_marks_dirty_and_stops(svc, prov):
    svc.enable("esc8", None)
    svc.enable("relay", None)
    prov.fail_on = {("relay", False)}
    assert not svc.disable("esc8", None, cascade=True)
    states = {e.name: e.status for e in svc.instance.scenarios}
    assert states == {"esc8": "enabled", "relay": "dirty"}


def test_reset_reverse_install_order(svc, prov):
    svc.enable("esc8", None)
    svc.enable("relay", None)
    prov.calls.clear()
    assert svc.reset()
    assert [c[0] for c in prov.calls] == ["relay", "esc8"]
    assert svc.instance.scenarios == []


def test_reapply_installs_in_order(svc, prov):
    svc.enable("esc8", None)
    svc.enable("relay", None)
    prov.calls.clear()
    assert svc.reapply()
    assert prov.calls == [("esc8", "dc01", True), ("relay", "dc01", True)]


def test_listing_hides_unavailable_unless_all(svc):
    names = [r[0] for r in svc.listing(False)]
    assert "unknown-cap-scenario" not in names
    assert "unknown-cap-scenario" in [r[0] for r in svc.listing(True)]


def test_listing_enabled_first(svc):
    svc.enable("esc8", None)
    rows = svc.listing(False)
    assert rows[0] == ("esc8", "enabled", "dc01")


def test_cascade_disables_dependent_on_every_target(svc, prov):
    svc.enable("esc8", None)
    svc.instance.add_scenario("relay", "dc01")
    svc.instance.add_scenario("relay", "srv03")
    prov.calls.clear()
    assert svc.disable("esc8", None, cascade=True)
    assert prov.calls == [("relay", "dc01", False), ("relay", "srv03", False), ("esc8", "dc01", False)]
    assert svc.instance.scenarios == []


def test_cascade_only_disables_dependents_in_same_domain(scenario_dir, tmp_path, prov):
    scenario_dir.make("maq", type="setting", touches=["dc.maq"])
    scenario_dir.make("rbcd", requires=["mssql"], target="mssql", depends=["maq"])
    domains = {"dc01": "sevenkingdoms.local", "dc02": "north.sevenkingdoms.local", "srv02": "north.sevenkingdoms.local"}
    resolver = ScenarioResolver(Scenarios(str(tmp_path)), "GOAD-Base", {"mssql": ["srv02"]}, "dc01",
                                ["dc01", "dc02"], host_domains=domains)
    svc = ScenarioService(FakeInstance(), FakeLab(resolver), prov)
    assert svc.enable("maq", "dc01")
    assert svc.enable("maq", "dc02")
    assert svc.enable("rbcd", None)
    assert svc.disable("maq", "dc01")
    assert [e.key for e in svc.instance.scenarios] == ["maq@dc02", "rbcd@srv02"]
