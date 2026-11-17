from goad.scenario import Scenario, Scenarios, InvalidScenario
import pytest

def test_from_file_loads_fields(scenario_dir):
    path = scenario_dir.make("esc8", type="setting", requires=["adcs"], target="adcs", touches=["adcs.web_enrollment"])
    s = Scenario.from_file("esc8", path)
    assert s.type == "setting"
    assert s.requires == ["adcs"]
    assert s.target == "adcs"
    assert s.touches == ["adcs.web_enrollment"]
    assert s.get_playbook(True) == "install.yml"
    assert s.get_playbook(False) == "uninstall.yml"

def test_invalid_type_rejected():
    with pytest.raises(InvalidScenario):
        Scenario("x", {"description": "d", "type": "bogus"})

def test_missing_optional_fields_default_empty():
    s = Scenario("x", {"description": "d", "type": "object"})
    assert s.requires == [] and s.depends == [] and s.target == "" and s.labs == ["*"]

def test_allowed_on_lab():
    assert Scenario("x", {"description": "d", "type": "object", "labs": ["GOAD-Base"]}).allowed_on_lab("GOAD-Base")
    assert not Scenario("x", {"description": "d", "type": "object", "labs": ["GOAD-Base"]}).allowed_on_lab("GOAD-Mini-Base")

def test_registry_skips_invalid_scenario(scenario_dir, tmp_path):
    scenario_dir.make("good")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "scenario.json").write_text("{not json")
    (tmp_path / "empty").mkdir()
    reg = Scenarios(str(tmp_path))
    assert [s.name for s in reg.all()] == ["good"]
    assert reg.get("broken") is None
