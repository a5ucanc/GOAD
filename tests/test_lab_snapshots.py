import os

import pytest

from goad.goadpath import GoadPath
from goad.instance import LabInstance
from goad.lab_snapshots import LabSnapshots

BASE_VMS = ["L-DC01", "L-DC02", "L-SRV02"]


class FakeProvider:
    def __init__(self):
        self.vms = list(BASE_VMS)
        self.snaps = {vm: [] for vm in self.vms}
        self.ext_vms = {"ws01": ["L-WS01"], "elk": ["L-ELK"]}
        self.calls = []
        self.fail_save_after = None   # save on this many VMs, then fail
        self.fail_restore = False
        self.fail_destroy = False

    def supports_named_snapshots(self):
        return True

    def vm_names(self):
        return list(self.vms)

    def snapshot_save(self, name):
        self.calls.append(("save", name))
        for i, vm in enumerate(self.vms):
            if self.fail_save_after is not None and i >= self.fail_save_after:
                return False
            self.snaps[vm].append(name)
        return True

    def snapshot_list(self):
        return {vm: list(names) for vm, names in self.snaps.items()}

    def snapshot_restore(self, name, vms):
        self.calls.append(("restore", name, list(vms)))
        return not self.fail_restore

    def snapshot_delete(self, name, vms):
        self.calls.append(("delete", name, list(vms)))
        for vm in vms:
            self.snaps[vm].remove(name)
        return True

    def destroy_vms(self, vms):
        self.calls.append(("destroy", list(vms)))
        if self.fail_destroy:
            return False
        for vm in vms:
            self.vms.remove(vm)
            self.snaps.pop(vm)
        return True

    def extension_vm_names(self, extension_name, lab_name, ip_range):
        return self.ext_vms.get(extension_name, [])

    def add_extension_vm(self, ext):
        for vm in self.ext_vms[ext]:
            self.vms.append(vm)
            self.snaps[vm] = []


@pytest.fixture
def inst(tmp_path, monkeypatch):
    ws = tmp_path / 'workspace'
    ws.mkdir()
    monkeypatch.setattr(GoadPath, 'get_workspace_path', staticmethod(lambda: str(ws)))
    i = LabInstance('abc', 'GOAD-Base', None, 'vmware', 'local', '192.168.56')
    os.makedirs(i.instance_path)
    i.save_json_instance()
    monkeypatch.setattr(i, "update_instance_folder", lambda: None)
    return i


@pytest.fixture
def prov():
    return FakeProvider()


@pytest.fixture
def snaps(inst, prov):
    return LabSnapshots(inst, prov, 'GOAD-Base', '192.168.56')


def enable(inst, snaps, name, target, snapshot=True):
    record = snaps.take("scn", f"{name}@{target}", f"{name}@{target}") if snapshot else None
    inst.add_scenario(name, target)
    return record


def test_take_records_state_and_name(inst, snaps, prov):
    enable(inst, snaps, "maq", "dc02")
    record = snaps.take("scn", "rbcd@srv02", "rbcd@srv02")
    assert record.name == "scn-02-rbcd@srv02"
    assert [s["name"] for s in record.scenarios] == ["maq"]
    assert inst.snapshots[-1] == record
    assert all("scn-02-rbcd@srv02" in prov.snaps[vm] for vm in BASE_VMS)


def test_take_failure_deletes_partial_snapshot(inst, snaps, prov):
    prov.fail_save_after = 1
    assert snaps.take("scn", "x@h", "x@h") is None
    assert all(names == [] for names in prov.snaps.values())
    assert inst.snapshots == []


def spec_example(inst, snaps):
    enable(inst, snaps, "maq", "dc02")
    enable(inst, snaps, "smb-signing-off", "srv02", snapshot=False)
    rbcd = enable(inst, snaps, "rbcd", "srv02")
    inst.remove_scenario("smb-signing-off", "srv02")
    enable(inst, snaps, "esc1", "dc01", snapshot=False)
    enable(inst, snaps, "esc4", "dc01")
    return rbcd


def test_report_lost_restored_removed(inst, snaps):
    rbcd = spec_example(inst, snaps)
    report = snaps.report(rbcd)
    assert report.removed == "rbcd@srv02"
    assert report.lost_scenarios == ["esc1@dc01", "esc4@dc01"]
    assert report.restored_scenarios == ["smb-signing-off@srv02"]
    assert report.deleted_snapshots == ["scn-03-esc4@dc01"]
    assert report.vagrant_change is None
    text = "\n".join(report.lines())
    assert "scn-02-rbcd@srv02" in text and "<- revert point" in text
    assert "lost:     esc1@dc01, esc4@dc01" in text
    assert "restored: smb-signing-off@srv02" in text


def test_report_vagrant_change_and_lost_extension_vms(inst, snaps):
    record = enable(inst, snaps, "maq", "dc02")
    inst.vagrant_disabled = True
    inst.extensions.append("ws01")
    report = snaps.report(record)
    assert report.vagrant_change == "vagrant account: enabled again"
    assert report.lost_extensions == {"ws01": ["L-WS01"]}
    assert "L-WS01" in "\n".join(report.lines())


def test_revertable_missing_snapshot_reason(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    prov.snaps["L-DC01"].remove(record.name)
    assert snaps.revertable(record) == f"snapshot {record.name} missing on L-DC01"


def test_revertable_ignores_vms_of_later_extensions(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    assert snaps.revertable(record) is None


def test_revert_restores_record_state_after_middle_uninstall(inst, snaps, prov):
    a = enable(inst, snaps, "a", "dc01")
    b = enable(inst, snaps, "b", "dc01")
    inst.remove_scenario("a", "dc01")
    snaps.forget("a@dc01")
    assert snaps.revert(b)
    assert [s.key for s in inst.scenarios] == ["a@dc01"]
    assert inst.snapshots == []
    assert all(names == [] for names in prov.snaps.values())
    assert snaps.find(a.taken_for) is None


def test_revert_destroys_later_extension_vms_then_restores_the_rest(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    assert snaps.revert(record)
    kinds = [c[0] for c in prov.calls]
    assert kinds.index("destroy") < kinds.index("restore")
    assert ("destroy", ["L-WS01"]) in prov.calls
    assert ("restore", record.name, BASE_VMS) in prov.calls
    assert inst.extensions == []
    assert inst.scenarios == []


def test_revert_failure_leaves_instance_unchanged(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    prov.fail_restore = True
    assert not snaps.revert(record)
    assert [s.key for s in inst.scenarios] == ["maq@dc02"]
    assert inst.snapshots == [record]


def test_forget_deletes_snapshot_and_record(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    snaps.forget("maq@dc02")
    assert inst.snapshots == []
    assert all(record.name not in names for names in prov.snaps.values())
    snaps.forget("nothing@here")


def test_revert_resyncs_clocks_after_restore(inst, prov):
    # restored VMs resume with the clock of the snapshot: the hook resets guest clocks
    order = []
    snaps = LabSnapshots(inst, prov, 'GOAD-Base', '192.168.56', after_restore=lambda: order.append("sync") or True)
    record = enable(inst, snaps, "maq", "dc02")
    assert snaps.revert(record)
    assert order == ["sync"]


def test_revert_clock_sync_failure_only_warns(inst, prov):
    snaps = LabSnapshots(inst, prov, 'GOAD-Base', '192.168.56', after_restore=lambda: False)
    record = enable(inst, snaps, "maq", "dc02")
    assert snaps.revert(record)
    assert inst.scenarios == []


def test_no_clock_sync_when_restore_fails(inst, prov):
    calls = []
    snaps = LabSnapshots(inst, prov, 'GOAD-Base', '192.168.56', after_restore=lambda: calls.append(1))
    record = enable(inst, snaps, "maq", "dc02")
    prov.fail_restore = True
    assert not snaps.revert(record)
    assert calls == []


def test_destroyed_extension_is_dropped_even_when_restore_fails(inst, snaps, prov):
    record = enable(inst, snaps, "maq", "dc02")
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    prov.fail_restore = True
    assert not snaps.revert(record)
    assert "ws01" not in inst.extensions
    assert [s.key for s in inst.scenarios] == ["maq@dc02"]


def test_no_revert_to_a_snapshot_listing_a_removed_extension(inst, snaps, prov):
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    record = enable(inst, snaps, "maq", "dc02")
    prov.destroy_vms(["L-WS01"])
    inst.extensions.remove("ws01")
    assert snaps.revertable(record) == f"extension ws01 in {record.name} is no longer installed"


def test_clock_sync_runs_after_the_state_is_applied(inst, prov):
    seen = []
    snaps = LabSnapshots(inst, prov, 'GOAD-Base', '192.168.56',
                         after_restore=lambda: seen.append(list(inst.extensions)) or True)
    record = enable(inst, snaps, "maq", "dc02")
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    assert snaps.revert(record)
    assert seen == [[]]


def test_rows_list_records_oldest_first_with_vm_presence(inst, snaps, prov):
    enable(inst, snaps, "maq", "dc02")
    second = enable(inst, snaps, "rbcd", "srv02")
    prov.snaps["L-DC01"].remove(second.name)
    rows = snaps.rows()
    assert rows == [
        ("scn-01-maq@dc02", "maq@dc02", "", "", "3/3"),
        ("scn-02-rbcd@srv02", "rbcd@srv02", "maq@dc02", "", "missing on L-DC01"),
    ]


def test_rows_show_orphan_goad_snapshots(inst, snaps, prov):
    for vm in prov.vms:
        prov.snaps[vm].append("scn-09-old@dc01")
    prov.snaps["L-DC01"].append("manual-backup")
    assert snaps.rows() == [("scn-09-old@dc01", "(no record)", "", "", "3/3"),
                            ("manual-backup", "(no record)", "", "", "1/3")]


def test_rows_show_extensions_in_record(inst, snaps, prov):
    inst.extensions.append("ws01")
    prov.add_extension_vm("ws01")
    snaps.take("scn", "x@h", "x@h")
    assert snaps.rows()[0][3] == "ws01"


def test_take_manual_names_and_records(inst, snaps, prov):
    enable(inst, snaps, "maq", "dc02", snapshot=False)
    first = snaps.take_manual("")
    second = snaps.take_manual("before esc8!")
    assert first.name == "snap-01-manual" and first.taken_for == "manual"
    assert second.name == "snap-02-before-esc8"
    assert [s["name"] for s in second.scenarios] == ["maq"]
    assert all(prov.snaps[vm] == ["snap-01-manual", "snap-02-before-esc8"] for vm in BASE_VMS)


def test_reset_revert_keeps_the_revert_point_and_later_snapshots(inst, snaps, prov):
    first = snaps.take_manual("a")
    enable(inst, snaps, "maq", "dc02")
    snaps.take_manual("b")
    report = snaps.report(first, keep_later=True)
    assert report.deleted_snapshots == [] and report.removed is None
    assert not any(line.startswith("  removed:") for line in report.lines())
    assert snaps.revert(first, keep_later=True)
    assert not [c for c in prov.calls if c[0] == "delete"]
    assert [r.name for r in inst.snapshots] == ["snap-01-a", "scn-02-maq@dc02", "snap-03-b"]
    assert inst.scenarios == []
    assert snaps.revert(first, keep_later=True)


def test_rows_show_unrecorded_and_grouped_push_snapshots(inst, snaps, prov):
    snaps.take_manual("")
    prov.snaps["L-DC01"] += ["push_1_1", "push_2_2", "by-hand"]
    prov.snaps["L-DC02"] += ["push_3_3"]
    assert snaps.rows()[1:] == [
        ("by-hand", "(no record)", "", "", "1/3"),
        ("push_* (2 per VM)", "(old snapshot command)", "", "", "2/3"),
    ]
