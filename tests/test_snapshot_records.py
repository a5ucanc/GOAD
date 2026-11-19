import json
import os

import pytest

from goad.goadpath import GoadPath
from goad.instance import LabInstance
from goad.instances import LabInstances
from goad.lab_snapshot_record import SnapshotRecord


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / 'workspace'
    ws.mkdir()
    monkeypatch.setattr(GoadPath, 'get_workspace_path', staticmethod(lambda: str(ws)))
    return ws


@pytest.fixture
def inst(workspace):
    i = LabInstance('abc-goad', 'GOAD', None, 'vmware', 'local', '192.168.56')
    os.makedirs(i.instance_path)
    i.save_json_instance()
    return i


def _record(name="scn-01-esc4@dc01", taken_for="esc4@dc01"):
    return SnapshotRecord(name, taken_for, [], False, [])


def test_snapshot_records_round_trip(inst):
    inst.next_snapshot_name("scn", "esc4@dc01")
    inst.add_snapshot_record(_record())
    loaded = LabInstances(None).get_instance('abc-goad')
    assert loaded.snapshots == [_record()]
    assert loaded.snapshot_seq == 2


def test_legacy_instance_has_no_snapshots(workspace):
    folder = workspace / 'x'
    folder.mkdir()
    (folder / 'instance.json').write_text(json.dumps({
        "id": "x", "lab": "GOAD", "provider": "vmware", "provisioner": "local",
        "ip_range": "192.168.56", "extensions": [], "status": "ready", "is_default": False}))
    loaded = LabInstances(None).get_instance('x')
    assert loaded.snapshots == []
    assert loaded.snapshot_seq == 1


def test_snapshot_name_counter_never_reused(inst):
    assert inst.next_snapshot_name("scn", "esc4@dc01") == "scn-01-esc4@dc01"
    second = inst.next_snapshot_name("ext", "ws01")
    assert second == "ext-02-ws01"
    inst.add_snapshot_record(_record(second, "extension:ws01"))
    inst.remove_snapshot_records([second])
    assert inst.snapshots == []
    assert inst.next_snapshot_name("scn", "x") == "scn-03-x"
    inst.snapshot_seq = 100
    assert inst.next_snapshot_name("scn", "x") == "scn-100-x"


def test_find_returns_latest_match(inst):
    inst.add_snapshot_record(_record("scn-01-a@h", "a@h"))
    inst.add_snapshot_record(_record("scn-02-a@h", "a@h"))
    assert inst.find_snapshot_record("a@h").name == "scn-02-a@h"
    assert inst.find_snapshot_record("b@h") is None


def test_capture_state_is_a_copy(inst):
    inst.add_scenario("maq", "dc02")
    inst.extensions.append("elk")
    record = inst.capture_state("scn-01-rbcd@srv02", "rbcd@srv02")
    inst.scenarios[0].status = "dirty"
    inst.extensions.append("ws01")
    assert record.scenarios[0]["status"] == "enabled"
    assert record.extensions == ["elk"]
    assert record.taken_for == "rbcd@srv02"


def test_apply_state_restores_fields(inst, monkeypatch):
    calls = []
    monkeypatch.setattr(inst, "update_instance_folder", lambda: calls.append(1))
    inst.add_scenario("maq", "dc02")
    record = inst.capture_state("scn-01-x", "x@h")
    inst.add_scenario("esc1", "dc01")
    inst.vagrant_disabled = True
    inst.extensions.append("ws01")
    inst.apply_state(record)
    assert [s.key for s in inst.scenarios] == ["maq@dc02"]
    assert inst.vagrant_disabled is False
    assert inst.extensions == []
    assert calls == [1]
    assert [s["name"] for s in json.load(open(inst.instance_path + '/instance.json'))["scenarios"]] == ["maq"]


def test_record_ignores_unknown_keys():
    r = SnapshotRecord.from_dict({"name": "n", "taken_for": "t", "scenarios": [], "vagrant_disabled": True,
                                  "extensions": ["elk"], "future": 1})
    assert r.vagrant_disabled is True and r.extensions == ["elk"]
