import json
import subprocess

import pytest
import yaml

BASE_LABS = ["GOAD-Mini-Base"]  # Task 10 extends this list


@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_lab_has_no_vulns(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    for h in cfg["hosts"].values():
        assert not h.get("vulns") and not h.get("vulns_vars") and not h.get("scripts")
    for d in cfg["domains"].values():
        assert not d.get("acls")
        for u in d["users"].values():
            assert u["password"] == "Aa1234567890!"
            assert not u.get("spns")
            assert "Aa1234567890" not in u.get("description", "")


@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_lab_passwords_uniform(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    assert all(d["domain_password"] == "Aa1234567890!" for d in cfg["domains"].values())
    assert all(h["local_admin_password"] == "Aa1234567890!" for h in cfg["hosts"].values())
    inv = open(f"ad/{lab}/data/inventory_disable_vagrant").read()
    assert "ansible_password=Aa1234567890!" in inv


@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_settings_cover_all_hosts_and_keys(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    assert set(cfg["base_settings"]) == set(cfg["hosts"])
    for host, settings in cfg["base_settings"].items():
        assert {"net.llmnr", "net.nbtns", "smb.signing", "kerberos.rc4", "firewall.state", "defender.realtime"} <= set(settings)


@pytest.mark.parametrize("lab", BASE_LABS)
def test_playbooks_entry_has_no_vuln_playbooks(lab):
    pb = yaml.safe_load(open("playbooks.yml"))[lab]
    assert "vulnerabilities.yml" not in pb and "security.yml" not in pb and "ad-acl.yml" not in pb
    assert pb[-1] == "hardening.yml"


def test_original_labs_untouched():
    assert subprocess.run(["git", "diff", "--quiet", "main", "--", "ad/GOAD", "ad/GOAD-Light", "ad/GOAD-Mini", "extensions/lx01", "extensions/ws01", "extensions/exchange"]).returncode == 0
