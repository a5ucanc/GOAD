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
        self.resolver_calls = []

    def get_scenario_resolver(self, extensions=()):
        self.resolver_calls.append(list(extensions))
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
    assert rows[0] == ("esc8", "enabled", "dc01", "")


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


def test_failed_install_and_failed_cleanup_marks_dirty(svc, prov):
    prov.fail_on = {("esc8", True), ("esc8", False)}
    assert not svc.enable("esc8", None)
    assert [(e.key, e.status) for e in svc.instance.scenarios] == [("esc8@dc01", "dirty")]


def test_reapply_skips_dirty_entries(svc, prov):
    assert svc.enable("esc8", None)
    svc.instance.mark_scenario_dirty("esc8", "dc01")
    prov.calls = []
    assert svc.reapply()
    assert prov.calls == []
    assert [(e.key, e.status) for e in svc.instance.scenarios] == [("esc8@dc01", "dirty")]


class FakeRecord:
    def __init__(self, name, taken_for):
        self.name = name
        self.taken_for = taken_for


class FakeReport:
    def lines(self):
        return ["report line"]


class FakeSnapshots:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.take_ok = True
        self.missing = None
        self.seq = 0

    def supported(self):
        return True

    def take(self, prefix, label, taken_for):
        self.calls.append(("take", taken_for))
        if not self.take_ok:
            return None
        self.seq += 1
        self.records[taken_for] = FakeRecord(f"{prefix}-{self.seq:02d}-{label}", taken_for)
        return self.records[taken_for]

    def find(self, taken_for):
        return self.records.get(taken_for)

    def revertable(self, record):
        return self.missing

    def report(self, record):
        return FakeReport()

    def revert(self, record):
        self.calls.append(("revert", record.name))
        return True

    def forget(self, taken_for):
        self.calls.append(("forget", taken_for))
        self.records.pop(taken_for, None)
        return True


@pytest.fixture
def snap_svc(svc):
    svc.snapshots = FakeSnapshots()
    svc.answers = []
    svc.ask = lambda prompt: (svc.answers.append(prompt), svc.yes)[1]
    svc.yes = True
    return svc


def test_enable_takes_snapshot_on_yes(snap_svc, prov):
    assert snap_svc.enable("esc8", None)
    assert snap_svc.answers == ["Take a lab snapshot before enabling esc8@dc01? (y/N)"]
    assert snap_svc.snapshots.calls == [("take", "esc8@dc01")]
    assert prov.calls == [("esc8", "dc01", True)]


def test_enable_no_snapshot_on_no(snap_svc):
    snap_svc.yes = False
    assert snap_svc.enable("esc8", None)
    assert snap_svc.snapshots.calls == []


def test_enable_no_prompt_without_ask(svc, prov):
    svc.snapshots = FakeSnapshots()
    assert svc.enable("esc8", None)
    assert svc.snapshots.calls == []


def test_no_snapshot_prompts_skips_snapshot_and_revert(snap_svc, prov):
    snap_svc.snapshot_prompts = False
    assert snap_svc.enable("esc8", None)
    assert snap_svc.disable("esc8", None)
    assert snap_svc.answers == []
    assert not any(c[0] in ("take", "revert") for c in snap_svc.snapshots.calls)
    assert ("esc8", "dc01", False) in prov.calls


def test_enable_refused_asks_nothing(snap_svc):
    assert not snap_svc.enable("esc8", "srv02")
    assert snap_svc.answers == []


def test_enable_stops_when_snapshot_fails(snap_svc, prov):
    snap_svc.snapshots.take_ok = False
    assert not snap_svc.enable("esc8", None)
    assert prov.calls == []
    assert snap_svc.instance.scenarios == []


def test_failed_enable_with_clean_cleanup_forgets_snapshot(snap_svc, prov):
    prov.fail_on = {("esc8", True)}
    assert not snap_svc.enable("esc8", None)
    assert ("forget", "esc8@dc01") in snap_svc.snapshots.calls


def test_failed_enable_dirty_keeps_snapshot(snap_svc, prov):
    prov.fail_on = {("esc8", True), ("esc8", False)}
    assert not snap_svc.enable("esc8", None)
    assert ("forget", "esc8@dc01") not in snap_svc.snapshots.calls
    assert snap_svc.snapshots.find("esc8@dc01") is not None


def test_disable_offers_revert_and_reverts_on_yes(snap_svc, prov):
    assert snap_svc.enable("esc8", None)
    prov.calls = []
    assert snap_svc.disable("esc8", None)
    assert snap_svc.answers[-1] == "Revert the lab to scn-01-esc8@dc01 instead of disabling? (y/N)"
    assert ("revert", "scn-01-esc8@dc01") in snap_svc.snapshots.calls
    assert prov.calls == []


def test_disable_revert_skips_dependents_check(snap_svc, prov):
    assert snap_svc.enable("esc8", None)
    snap_svc.yes = False
    assert snap_svc.enable("relay", None)
    snap_svc.yes = True
    assert snap_svc.disable("esc8", None)
    assert ("revert", "scn-01-esc8@dc01") in snap_svc.snapshots.calls


def test_disable_declined_revert_uninstalls_and_forgets(snap_svc, prov):
    assert snap_svc.enable("esc8", None)
    snap_svc.yes = False
    assert snap_svc.disable("esc8", None)
    assert ("esc8", "dc01", False) in prov.calls
    assert ("forget", "esc8@dc01") in snap_svc.snapshots.calls
    assert snap_svc.instance.scenarios == []


def test_disable_missing_snapshot_uninstalls_without_asking(snap_svc, prov):
    assert snap_svc.enable("esc8", None)
    snap_svc.snapshots.missing = "snapshot scn-01-esc8@dc01 missing on L-DC01"
    asked = len(snap_svc.answers)
    assert snap_svc.disable("esc8", None)
    assert len(snap_svc.answers) == asked
    assert ("esc8", "dc01", False) in prov.calls


def test_reset_forgets_snapshots(snap_svc):
    assert snap_svc.enable("esc8", None)
    assert snap_svc.reset()
    assert ("forget", "esc8@dc01") in snap_svc.snapshots.calls


def test_listing_shows_snapshot_column(snap_svc):
    assert snap_svc.enable("esc8", None)
    rows = snap_svc.listing(False)
    assert rows[0] == ("esc8", "enabled", "dc01", "scn-01-esc8@dc01")
    assert all(len(row) == 4 for row in rows)


def test_service_passes_instance_extensions(svc):
    svc.instance.extensions = ["mssql"]
    svc.listing(False)
    svc.enable("esc8", None)
    assert svc.lab.resolver_calls
    assert all(call == ["mssql"] for call in svc.lab.resolver_calls)


class ExtLab(FakeLab):
    """Lab whose mssql capabilities come from the mssql extension unless base_caps already grants them."""

    def __init__(self, scenarios, base_caps, ext_caps):
        self.scenarios = scenarios
        self.base_caps = base_caps
        self.ext_caps = ext_caps
        self.resolver_calls = []

    def effective_capabilities(self, extensions=()):
        caps = {k: list(v) for k, v in self.base_caps.items()}
        if "mssql" in extensions:
            for k, hosts in self.ext_caps.items():
                caps.setdefault(k, [])
                caps[k] += [h for h in hosts if h not in caps[k]]
        return caps

    def get_scenario_resolver(self, extensions=()):
        self.resolver_calls.append(list(extensions))
        return ScenarioResolver(self.scenarios, "GOAD-Base", self.effective_capabilities(extensions), "dc01",
                                ["dc01", "dc02"])

    def get_scenario(self, name):
        return self.scenarios.get(name)


@pytest.fixture
def ext_svc(scenario_dir, tmp_path, prov):
    scenario_dir.make("esc8", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    scenario_dir.make("mssql-sysadmin", requires=["mssql"], target="mssql")
    scenario_dir.make("mssql-linked", requires=["mssql_link"], target="mssql_link")
    scenario_dir.make("relay", depends=["mssql-sysadmin"])
    inst = FakeInstance()
    inst.extensions = ["mssql"]

    def build(base_caps=None):
        lab = ExtLab(Scenarios(str(tmp_path)), base_caps or {"adcs": ["dc01"]},
                     {"mssql": ["srv02", "srv03"], "mssql_link": ["srv02"]})
        return ScenarioService(inst, lab, prov)
    return build


def _keys(entries):
    return [e.key for e in entries]


def test_affected_by_removal_target(ext_svc):
    svc = ext_svc()
    svc.instance.scenarios = [EnabledScenario("mssql-sysadmin", "srv02", "t")]
    assert _keys(svc.affected_by_extension_removal("mssql")) == ["mssql-sysadmin@srv02"]


def test_affected_by_removal_includes_dependents_first(ext_svc):
    svc = ext_svc()
    svc.instance.scenarios = [EnabledScenario("mssql-sysadmin", "srv02", "t"),
                              EnabledScenario("relay", "dc01", "t"),
                              EnabledScenario("mssql-linked", "srv02", "t")]
    keys = _keys(svc.affected_by_extension_removal("mssql"))
    assert sorted(keys) == ["mssql-linked@srv02", "mssql-sysadmin@srv02", "relay@dc01"]
    assert keys.index("relay@dc01") < keys.index("mssql-sysadmin@srv02")


def test_affected_ignores_unrelated(ext_svc):
    svc = ext_svc()
    svc.instance.scenarios = [EnabledScenario("esc8", "dc01", "t")]
    assert svc.affected_by_extension_removal("mssql") == []


def test_affected_kept_when_lab_grants(ext_svc):
    svc = ext_svc({"adcs": ["dc01"], "mssql": ["srv02"]})
    svc.instance.scenarios = [EnabledScenario("mssql-sysadmin", "srv02", "t"),
                              EnabledScenario("mssql-sysadmin", "srv03", "t")]
    assert _keys(svc.affected_by_extension_removal("mssql")) == ["mssql-sysadmin@srv03"]


def test_disable_entries_stops_on_failure(ext_svc, prov):
    svc = ext_svc()
    svc.instance.scenarios = [EnabledScenario("relay", "dc01", "t"), EnabledScenario("mssql-sysadmin", "srv02", "t")]
    prov.fail_on = {("relay", False)}
    assert not svc.disable_entries(list(svc.instance.scenarios))
    assert prov.calls == [("relay", "dc01", False)]
    assert [(e.key, e.status) for e in svc.instance.scenarios] == [("relay@dc01", "dirty"),
                                                                   ("mssql-sysadmin@srv02", "enabled")]


def test_disable_entries_all(ext_svc, prov):
    svc = ext_svc()
    svc.instance.scenarios = [EnabledScenario("relay", "dc01", "t"), EnabledScenario("mssql-sysadmin", "srv02", "t")]
    assert svc.disable_entries(list(svc.instance.scenarios))
    assert svc.instance.scenarios == []
