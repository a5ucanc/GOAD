from pathlib import Path

import yaml

from goad.provisioner.ansible.ansible import Ansible

ROOT = Path(__file__).resolve().parent.parent


def test_sync_time_playbook_sets_windows_clocks_from_controller_utc():
    plays = yaml.safe_load((ROOT / "ansible" / "sync_time.yml").read_text())
    assert plays[0]["hosts"] == "domain"
    text = (ROOT / "ansible" / "sync_time.yml").read_text()
    assert "Set-Date" in text and "date -u" in text


def test_run_sync_time_uses_disable_vagrant_and_lab_inventories(monkeypatch):
    prov = Ansible.__new__(Ansible)
    monkeypatch.setattr(prov, "_get_disable_vagrant_lab_inventory", lambda: ["dv"])
    monkeypatch.setattr(prov, "_get_lab_inventory", lambda lab, provider: ["lab"])
    monkeypatch.setattr(prov, "_get_global_inventory", lambda: "global")
    prov.lab_name, prov.provider_name = "GOAD-Base", "vmware"
    seen = {}
    monkeypatch.setattr(prov, "run_playbook", lambda playbook, inventories, **kw: seen.update(p=playbook, i=inventories) or True)
    assert prov.run_sync_time()
    assert seen == {"p": "sync_time.yml", "i": ["dv", "lab", "global"]}


def test_snapshot_docs_describe_restore_and_clock_sync():
    text = (ROOT / "docs" / "mkdocs" / "docs" / "scenarios.md").read_text()
    section = text[text.index("### Snapshots"):text.index("### Re-provisioning")]
    assert "vmrun" in section
    assert "sync_time.yml" in section
    assert "partially reverted" in section
