import json
import os

import pytest

from goad.goadpath import GoadPath
from goad.instance import LabInstance
from goad.instances import LabInstances
from goad.labs import Lab, Labs


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / 'workspace'
    ws.mkdir()
    monkeypatch.setattr(GoadPath, 'get_workspace_path', staticmethod(lambda: str(ws)))
    return ws


@pytest.fixture
def tmp_instance(workspace):
    inst = LabInstance('abc-goad', 'GOAD', None, 'virtualbox', 'local', '192.168.56')
    os.makedirs(inst.instance_path)
    inst.save_json_instance()
    return inst


def _read(inst):
    with open(inst.instance_path + '/instance.json') as f:
        return json.load(f)


def test_load_legacy_instance_without_scenarios(workspace):
    folder = workspace / 'x'
    folder.mkdir()
    (folder / 'instance.json').write_text(json.dumps({
        "id": "x", "lab": "GOAD", "provider": "virtualbox", "provisioner": "local",
        "ip_range": "192.168.56", "extensions": [], "status": "ready", "is_default": False}))
    insts = LabInstances(None)
    assert insts.get_instance('x').scenarios == []
    assert insts.get_instance('x').vagrant_disabled is False


def test_vagrant_disabled_roundtrip(tmp_instance):
    assert _read(tmp_instance)["vagrant_disabled"] is False
    tmp_instance.set_vagrant_disabled(True)
    assert _read(tmp_instance)["vagrant_disabled"] is True
    assert LabInstances(None).get_instance('abc-goad').vagrant_disabled is True


def test_add_remove_dirty_roundtrip(tmp_instance):
    tmp_instance.add_scenario("esc8", "dc01")
    data = _read(tmp_instance)
    assert data["scenarios"][0]["status"] == "enabled"
    assert data["scenarios"][0]["enabled_at"].endswith("Z")
    tmp_instance.mark_scenario_dirty("esc8", "dc01")
    data = _read(tmp_instance)
    assert data["scenarios"][0]["name"] == "esc8"
    assert data["scenarios"][0]["target"] == "dc01"
    assert data["scenarios"][0]["status"] == "dirty"
    tmp_instance.remove_scenario("esc8", "dc01")
    assert _read(tmp_instance)["scenarios"] == []


def test_instance_loads_scenarios_from_dicts(workspace):
    inst = LabInstance('a', 'GOAD', None, 'virtualbox', 'local', '1.1.1',
                       scenarios=[{"name": "n", "target": "t", "enabled_at": "x", "status": "dirty"}])
    assert inst.scenarios[0].key == "n@t"
    assert inst.scenarios[0].status == "dirty"


def test_instance_ignores_unknown_scenario_keys(workspace):
    inst = LabInstance('a', 'GOAD', None, 'virtualbox', 'local', '1.1.1',
                       scenarios=[{"name": "n", "target": "t", "enabled_at": "x", "extra": 1}])
    assert inst.scenarios[0].key == "n@t"
    assert inst.scenarios[0].status == "enabled"


def _write_config(root, lab, config):
    data = root / lab / 'data'
    data.mkdir(parents=True)
    if config is not None:
        (data / 'config.json').write_text(config if isinstance(config, str) else json.dumps(config))


@pytest.fixture
def build_lab(tmp_path, monkeypatch):
    monkeypatch.setattr(Lab, '_load_providers', lambda self, n, c: None)
    monkeypatch.setattr(Lab, '_load_extensions', lambda self, n: None)
    monkeypatch.setattr(GoadPath, 'get_lab_data_path',
                        staticmethod(lambda n: str(tmp_path / n / 'data')))

    def build(name, config):
        _write_config(tmp_path, name, config)
        return Lab(name, None)
    return build


GOAD_CONFIG = {"lab": {
    "capabilities": {"adcs": ["dc01"]},
    "hosts": {
        "dc03": {"type": "dc", "domain": "essos.local"},
        "dc02": {"type": "dc", "domain": "north.sevenkingdoms.local"},
        "dc01": {"type": "dc", "domain": "sevenkingdoms.local"},
        "srv02": {"type": "server", "domain": "north.sevenkingdoms.local"},
    },
    "domains": {
        "essos.local": {"dc": "dc03"},
        "north.sevenkingdoms.local": {"dc": "dc02"},
        "sevenkingdoms.local": {"dc": "dc01"},
    }}}


def test_lab_capabilities_and_root_dc(build_lab):
    lab = build_lab("GOAD-Base", GOAD_CONFIG)
    assert lab.is_base()
    assert lab.capabilities == {"adcs": ["dc01"]}
    assert lab.root_dc == "dc01"
    assert sorted(lab.dcs) == ["dc01", "dc02", "dc03"]


def test_root_dc_tie_picks_lowest_key(build_lab):
    cfg = {"lab": {"capabilities": {}, "hosts": {}, "domains": {
        "b.local": {"dc": "dc02"}, "a.local": {"dc": "dc01"}}}}
    assert build_lab("L", cfg).root_dc == "dc01"


def test_lab_without_capabilities_is_not_base(build_lab):
    cfg = {"lab": {"hosts": GOAD_CONFIG["lab"]["hosts"], "domains": GOAD_CONFIG["lab"]["domains"]}}
    lab = build_lab("GOAD", cfg)
    assert not lab.is_base()
    assert lab.capabilities is None


@pytest.mark.parametrize("config", [None, "not json", "[]", '{"lab": 3}'])
def test_odd_config_never_raises(build_lab, config):
    lab = build_lab("X", config)
    assert lab.capabilities is None
    assert lab.dcs == []
    assert lab.root_dc == ""
    assert not lab.is_base()


def test_scenario_registry(build_lab, scenario_dir, monkeypatch):
    path = scenario_dir.make("kerberoast")
    monkeypatch.setattr(GoadPath, 'get_scenarios_path',
                        staticmethod(lambda: os.path.dirname(os.path.dirname(path))))
    lab = build_lab("GOAD-Base", GOAD_CONFIG)
    resolver = lab.get_scenario_resolver()
    assert resolver is lab.get_scenario_resolver()
    assert resolver.root_dc == "dc01"
    assert lab.get_scenario("kerberoast").name == "kerberoast"
    assert lab.get_scenario("nope") is None
