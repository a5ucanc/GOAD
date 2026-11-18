import json
import os
import subprocess

import pytest
import yaml

BASE_LABS = ["GOAD-Mini-Base", "GOAD-Light-Base", "GOAD-Base"]


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


ACCEPTED = {
    "net.llmnr": {"disabled", "enabled"},
    "net.nbtns": {"disabled", "enabled"},
    "net.mdns": {"disabled", "enabled"},
    "smb.signing": {"required", "optional"},
    "ldap.signing": {"required", "none"},
    "ldap.channel_binding": {"always", "never"},
    "kerberos.rc4": {"disabled", "enabled"},
    "ntlm.lmcompat": {"0", "1", "2", "3", "4", "5"},
    "defender.realtime": {"on", "off"},
    "firewall.state": {"on", "off"},
    "dc.maq": {str(i) for i in range(11)},
    "host.tier": {"0", "1", "2"},
    "dc.spooler": {"disabled", "enabled"},
    "dc.strong_cert_binding": {"0", "1", "2"},
    "adcs.web_enrollment": {"false", "true"},
    "adcs.editf_san": {"off", "on"},
    "adcs.enforce_encrypt": {"on", "off"},
}


@pytest.mark.parametrize("lab", BASE_LABS)
def test_base_settings_values_accepted_by_role(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    for host, settings in cfg["base_settings"].items():
        for key, value in settings.items():
            assert key in ACCEPTED, f"{host}: unknown key {key}"
            assert str(value).lower() in ACCEPTED[key], f"{host}: {key}={value!r}"
            task = f"ansible/roles/base_setting/tasks/{key.replace('.', '_')}.yml"
            assert os.path.exists(task), task


@pytest.mark.parametrize("lab", BASE_LABS)
def test_playbooks_entry_has_no_vuln_playbooks(lab):
    pb = yaml.safe_load(open("playbooks.yml"))[lab]
    assert "vulnerabilities.yml" not in pb and "ad-acl.yml" not in pb
    assert pb[-1] == "hardening.yml"


def test_original_labs_untouched():
    assert subprocess.run(["git", "diff", "--quiet", "main", "--", "ad/GOAD", "ad/GOAD-Light", "ad/GOAD-Mini", "extensions/lx01", "extensions/ws01", "extensions/exchange"]).returncode == 0


def _inventory_group(lab, group):
    hosts, current = [], None
    for line in open(f"ad/{lab}/data/inventory").read().splitlines():
        line = line.strip()
        if line.startswith("["):
            current = line.strip("[]")
        elif current == group and line and not line.startswith(";"):
            hosts.append(line.split()[0])
    return hosts


@pytest.mark.parametrize("lab", BASE_LABS)
def test_laps_capability_matches_laps_hosts(lab):
    cfg = json.load(open(f"ad/{lab}/data/config.json"))["lab"]
    laps_hosts = {h for h, v in cfg["hosts"].items() if v.get("use_laps")}
    laps_hosts |= set(_inventory_group(lab, "laps_server")) | set(_inventory_group(lab, "laps_workstation"))
    capability = (cfg.get("capabilities") or {}).get("laps")
    if laps_hosts:
        assert sorted(capability) == sorted(laps_hosts)
    else:
        assert capability is None
