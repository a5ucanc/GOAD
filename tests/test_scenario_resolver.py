import pytest

from goad.scenario import Scenarios
from goad.scenario_resolver import ScenarioResolver, EnabledScenario, ScenarioRefused


@pytest.fixture
def scenarios(tmp_path, scenario_dir):
    make = scenario_dir.make
    make("kerberoast")
    make("esc1", requires=["adcs"], target="adcs")
    make("esc8", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    make("esc8-alt", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    make("relay", depends=["esc8"])
    make("relay2", depends=["relay"])
    make("hardened-ca", conflicts=["esc8"])
    return Scenarios(str(tmp_path))


@pytest.fixture
def resolver(scenarios):
    return ScenarioResolver(scenarios, "GOAD-Base", {"adcs": ["dc01", "srv03"], "mssql": ["srv02"]},
                            "dc01", ["dc01", "dc02", "dc03"])


@pytest.fixture
def resolver_no_adcs(scenarios):
    return ScenarioResolver(scenarios, "GOAD-Base", {"mssql": ["srv02"]}, "dc01", ["dc01", "dc02", "dc03"])


@pytest.fixture
def cyclic_resolver(tmp_path, scenario_dir):
    scenario_dir.make("a", depends=["b"])
    scenario_dir.make("b", depends=["a"])
    return ScenarioResolver(Scenarios(str(tmp_path)), "GOAD-Base", {}, "dc01", ["dc01"])


def test_capability_target_defaults_to_first_host(resolver):
    assert resolver.check_enable("esc8", None, []) == "dc01"


def test_named_target_used(resolver):
    assert resolver.check_enable("esc8", "srv03", []) == "srv03"


def test_target_not_in_capability_refused(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("esc8", "srv02", [])
    assert "host srv02 does not provide adcs" in e.value.reasons


def test_domain_wide_defaults_to_root_dc(resolver):
    assert resolver.check_enable("kerberoast", None, []) == "dc01"
    assert resolver.check_enable("kerberoast", "dc03", []) == "dc03"


def test_domain_wide_non_dc_refused(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("kerberoast", "srv03", [])
    assert "host srv03 is not a domain controller" in e.value.reasons


def test_missing_capability(resolver_no_adcs):
    with pytest.raises(ScenarioRefused) as e:
        resolver_no_adcs.check_enable("esc1", None, [])
    assert e.value.reasons == ["missing capability adcs"]


def test_lab_without_capabilities_offers_nothing(scenarios):
    r = ScenarioResolver(scenarios, "GOAD", None, "dc01", ["dc01"])
    assert all(reasons == ["lab GOAD does not support scenarios"] for _, reasons in r.available([]))


def test_unknown_scenario(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("nope", None, [])
    assert e.value.reasons == ["unknown scenario nope"]


def test_available_lists_reasons(resolver):
    got = {s.name: reasons for s, reasons in resolver.available([])}
    assert got["kerberoast"] == []
    assert got["relay"] == ["requires scenario esc8"]


def test_touches_conflict_same_host_only(resolver):
    on = [EnabledScenario("esc8", "dc01", "t")]
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("esc8-alt", "dc01", on)
    assert "esc8@dc01 already changes adcs.web_enrollment on dc01" in e.value.reasons
    assert resolver.check_enable("esc8-alt", "srv03", on) == "srv03"


def test_same_scenario_two_targets(resolver):
    on = [EnabledScenario("esc8", "dc01", "t")]
    assert resolver.check_enable("esc8", "srv03", on) == "srv03"
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8", "dc01", on)


def test_conflicts_both_directions(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("hardened-ca", None, [EnabledScenario("esc8", "dc01", "t")])
    assert "conflicts with esc8@dc01" in e.value.reasons
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8", "srv03", [EnabledScenario("hardened-ca", "dc01", "t")])


def test_depends_required(resolver):
    with pytest.raises(ScenarioRefused) as e:
        resolver.check_enable("relay", None, [])
    assert "requires scenario esc8" in e.value.reasons


def test_dirty_still_conflicts(resolver):
    with pytest.raises(ScenarioRefused):
        resolver.check_enable("esc8-alt", "dc01", [EnabledScenario("esc8", "dc01", "t", "dirty")])


def test_install_order(resolver):
    assert resolver.install_order(["relay2", "esc8", "relay"]) == ["esc8", "relay", "relay2"]


def test_install_order_cycle_raises(cyclic_resolver):
    with pytest.raises(ScenarioRefused):
        cyclic_resolver.install_order(["a", "b"])


def test_install_order_unknown_raises(resolver):
    with pytest.raises(ScenarioRefused):
        resolver.install_order(["nope"])


def test_dependents_deepest_first(resolver):
    on = [EnabledScenario("esc8", "dc01", "t"), EnabledScenario("relay", "dc01", "t"), EnabledScenario("relay2", "dc01", "t")]
    assert [e.name for e in resolver.dependents("esc8", on)] == ["relay2", "relay"]


def test_dependents_include_every_target_of_a_dependent(resolver):
    on = [EnabledScenario("esc8", "dc01", "t"), EnabledScenario("relay", "dc01", "t"), EnabledScenario("relay", "srv03", "t")]
    keys = [e.key for e in resolver.dependents("esc8", on)]
    assert keys == ["relay@dc01", "relay@srv03"]


HOST_DOMAINS = {"dc01": "sevenkingdoms.local", "dc02": "north.sevenkingdoms.local",
                "srv02": "north.sevenkingdoms.local", "dc03": "essos.local", "srv03": "essos.local"}


@pytest.fixture
def domain_resolver(scenarios, scenario_dir, tmp_path):
    scenario_dir.make("maq", type="setting", touches=["dc.maq"])
    scenario_dir.make("rbcd", requires=["mssql"], target="mssql", depends=["maq"])
    return ScenarioResolver(Scenarios(str(tmp_path)), "GOAD-Base", {"adcs": ["dc01", "srv03"], "mssql": ["srv02"]},
                            "dc01", ["dc01", "dc02", "dc03"], host_domains=HOST_DOMAINS)


def test_dependency_in_same_domain_is_met(domain_resolver):
    on = [EnabledScenario("maq", "dc02", "t")]
    assert domain_resolver.check_enable("rbcd", None, on) == "srv02"


def test_dependency_in_other_domain_is_refused(domain_resolver):
    on = [EnabledScenario("maq", "dc01", "t")]
    with pytest.raises(ScenarioRefused) as e:
        domain_resolver.check_enable("rbcd", None, on)
    assert "requires scenario maq in domain north.sevenkingdoms.local" in e.value.reasons


def test_dependents_filtered_by_domain(domain_resolver):
    on = [EnabledScenario("maq", "dc01", "t"), EnabledScenario("maq", "dc02", "t"),
          EnabledScenario("rbcd", "srv02", "t")]
    assert domain_resolver.dependents("maq", on, "dc01") == []
    assert [e.key for e in domain_resolver.dependents("maq", on, "dc02")] == ["rbcd@srv02"]


def test_without_host_domains_any_host_meets_dependency(resolver):
    on = [EnabledScenario("esc8", "srv03", "t")]
    assert resolver.check_enable("relay", None, on) == "dc01"


def test_available_when_a_non_default_target_meets_dependency(scenario_dir, tmp_path):
    scenario_dir.make("maq", type="setting", touches=["dc.maq"])
    scenario_dir.make("rbcd", requires=["mssql"], target="mssql", depends=["maq"])
    r = ScenarioResolver(Scenarios(str(tmp_path)), "GOAD-Base", {"mssql": ["srv02", "srv03"]},
                         "dc01", ["dc01", "dc02", "dc03"], host_domains=HOST_DOMAINS)
    on = [EnabledScenario("maq", "dc03", "t")]
    reasons = dict((s.name, why) for s, why in r.available(on))
    assert reasons["rbcd"] == []
