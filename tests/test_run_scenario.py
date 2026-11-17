import pytest
import os
from goad.provisioner.ansible.ansible import Ansible
from goad.scenario import Scenario


class _Prov(Ansible):
    def __init__(self, path, run_playbook):
        self.instance_path = str(path)
        self.lab_name = "GOAD"
        self.provider_name = "virtualbox"
        self._rp = run_playbook

    def _get_global_inventory(self):
        return None

    def run_playbook(self, playbook, inventories, tries=3, timeout=30, playbook_path=None):
        return self._rp(playbook, inventories, tries, timeout, playbook_path)


def make_ansible_stub(tmp_path, run_playbook):
    (tmp_path / "inventory_disable_vagrant").write_text("")
    return _Prov(tmp_path, run_playbook)


def test_run_scenario_inventory_and_playbook(tmp_path, scenario_dir):
    calls = []
    prov = make_ansible_stub(tmp_path, lambda pb, inv, tries=3, timeout=30, playbook_path=None: calls.append((pb, inv, playbook_path)) or True)
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", [], install=False)
    pb, inv, path = calls[0]
    assert pb == "uninstall.yml"
    assert inv[0].endswith("inventory_disable_vagrant")
    assert inv[-1].endswith("scenario_run_inventory")
    assert path == s.get_ansible_path() + os.path.sep
    content = open(inv[-1]).read()
    assert "[scenario_target]\nsrv03\n" in content
    assert "scenario_name=esc8" in content and "scenario_target=srv03" in content


def test_run_scenario_only_includes_existing_extension_inventories(tmp_path, scenario_dir):
    calls = []
    prov = make_ansible_stub(tmp_path, lambda pb, inv, tries=3, timeout=30, playbook_path=None: calls.append(inv) or True)
    (tmp_path / "ext1_inventory").write_text("")
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", ["ext1", "ext2"])
    names = [os.path.basename(i) for i in calls[0]]
    assert names == ["inventory_disable_vagrant", "ext1_inventory", "scenario_run_inventory"]


def test_run_scenario_failure_returns_false(tmp_path, scenario_dir):
    prov = make_ansible_stub(tmp_path, lambda *a: False)
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", []) is False


class _Extension:
    name = "elk"

    def get_playbook(self, install=True):
        return "install.yml" if install else "uninstall.yml"

    def get_ansible_path(self):
        return "/ext/elk/ansible/"


def _make_extension_prov(tmp_path, monkeypatch, calls):
    from goad.goadpath import GoadPath
    lab_inventory = tmp_path / "lab_inventory"
    lab_inventory.write_text("")
    (tmp_path / "inventory").write_text("")
    (tmp_path / "global_inventory").write_text("")
    monkeypatch.setattr(GoadPath, "get_lab_inventory_file", staticmethod(lambda lab: str(lab_inventory)))
    prov = make_ansible_stub(tmp_path, lambda pb, inv, tries=3, timeout=30, playbook_path=None: calls.append(inv) or True)
    prov._get_global_inventory = lambda: str(tmp_path / "global_inventory")
    return prov


def test_run_extension_default_uses_vagrant_inventory(tmp_path, monkeypatch):
    calls = []
    prov = _make_extension_prov(tmp_path, monkeypatch, calls)
    assert prov.run_extension(_Extension(), ["elk", "ws01"])
    names = [os.path.basename(i) for i in calls[0]]
    assert names == ["lab_inventory", "inventory", "ws01_inventory", "elk_inventory", "global_inventory"]


def test_run_extension_disable_vagrant_inventory(tmp_path, monkeypatch):
    calls = []
    prov = _make_extension_prov(tmp_path, monkeypatch, calls)
    assert prov.run_extension(_Extension(), ["elk", "ws01"], use_disable_vagrant_inventory=True)
    names = [os.path.basename(i) for i in calls[0]]
    assert names == ["inventory_disable_vagrant", "ws01_inventory", "elk_inventory", "global_inventory"]


def test_run_scenario_syncs_jumpbox_after_writing_run_inventory(tmp_path, scenario_dir):
    events = []
    inventory = tmp_path / "scenario_run_inventory"

    def run_playbook(pb, inv, tries=3, timeout=30, playbook_path=None):
        events.append("run_playbook")
        return True

    prov = make_ansible_stub(tmp_path, run_playbook)
    prov.use_jumpbox = True
    prov.sync_source_jumpbox = lambda: events.append("sync:" + inventory.read_text().splitlines()[1])
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", [])
    assert prov.run_scenario(s, "dc01", [])
    assert events == ["sync:srv03", "run_playbook", "sync:dc01", "run_playbook"]


def test_run_scenario_local_provisioner_does_not_sync(tmp_path, scenario_dir):
    prov = make_ansible_stub(tmp_path, lambda *a, **k: True)
    prov.sync_source_jumpbox = lambda: pytest.fail("sync called without jumpbox")
    s = Scenario.from_file("esc8", scenario_dir.make("esc8", type="setting"))
    assert prov.run_scenario(s, "srv03", [])
