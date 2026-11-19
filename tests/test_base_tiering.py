import json

import pytest
import yaml

from tests.test_base_lab_configs import _inventory_group

BASE_LABS = ["GOAD-Mini-Base", "GOAD-Light-Base", "GOAD-Base"]
TIERS = {"T0-Admins", "T1-ServerAdmins", "T2-WorkstationAdmins"}
ADMIN_GROUPS = TIERS | {"Domain Admins"}
T0 = {"sevenkingdoms.local": {"cersei.lannister", "robert.baratheon"},
      "north.sevenkingdoms.local": {"eddard.stark"}, "essos.local": {"daenerys.targaryen"}}
T1 = {"north.sevenkingdoms.local": {"jeor.mormont"}, "essos.local": {"khal.drogo"}}
# services come from the mssql / iis extensions: no Base lab grants these capabilities itself
CAPABILITIES = {
    "GOAD-Base": {},
    "GOAD-Light-Base": {},
    "GOAD-Mini-Base": {},
}


def load(lab):
    return json.load(open(f"ad/{lab}/data/config.json"))["lab"]


def members(domain, group):
    return {u for u, v in domain["users"].items() if group in v.get("groups", [])}


def domain_dn(name):
    return ",".join(f"DC={part}" for part in name.split("."))


@pytest.mark.parametrize("lab", BASE_LABS)
def test_tier_groups_in_every_domain(lab):
    for name, domain in load(lab)["domains"].items():
        groups = domain["groups"]["global"]
        assert TIERS <= set(groups)
        for tier in TIERS:
            assert groups[tier]["path"].lower() == f"CN=Users,{domain_dn(name)}".lower()


@pytest.mark.parametrize("lab", BASE_LABS)
def test_t0_members_are_protected(lab):
    for name, domain in load(lab)["domains"].items():
        assert members(domain, "T0-Admins") == T0[name]
        assert members(domain, "Domain Admins") == T0[name]
        assert T0[name] <= members(domain, "Protected Users")


@pytest.mark.parametrize("lab", BASE_LABS)
def test_t1_members(lab):
    for name, domain in load(lab)["domains"].items():
        assert members(domain, "T1-ServerAdmins") == T1.get(name, set())
        assert members(domain, "T2-WorkstationAdmins") == set()


@pytest.mark.parametrize("lab", BASE_LABS)
def test_nobody_else_has_admin_groups(lab):
    for name, domain in load(lab)["domains"].items():
        admins = T0[name] | T1.get(name, set())
        for user, v in domain["users"].items():
            if user not in admins:
                assert not ADMIN_GROUPS & set(v.get("groups", [])), user


@pytest.mark.parametrize("lab", BASE_LABS)
def test_dc_local_groups_empty(lab):
    for host, v in load(lab)["hosts"].items():
        if v["type"] == "dc":
            groups = v.get("local_groups") or {}
            assert not groups.get("Administrators") and not groups.get("Remote Desktop Users"), host


@pytest.mark.parametrize("lab", BASE_LABS)
def test_server_local_admins_are_t1(lab):
    cfg = load(lab)
    for host, v in cfg["hosts"].items():
        if v["type"] == "server":
            nb = cfg["domains"][v["domain"]]["netbios_name"].lower()
            assert v["local_groups"]["Administrators"] == [f"{nb}\\T1-ServerAdmins"], host


@pytest.mark.parametrize("lab", BASE_LABS)
def test_host_tier_values(lab):
    cfg = load(lab)
    for host, v in cfg["hosts"].items():
        assert cfg["base_settings"][host]["host.tier"] == (0 if v["type"] == "dc" else 1), host


@pytest.mark.parametrize("lab", BASE_LABS)
def test_capabilities(lab):
    caps = load(lab)["capabilities"]
    for cap in ("iis", "mssql_link"):
        assert caps.get(cap) == CAPABILITIES[lab].get(cap), cap


ASR_LSASS = "9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2"
EXCLUDED_SECURITY = {"maq0_client", "maq0_server", "powershell_restrict", "ldaps", "files", "directory"}


@pytest.mark.parametrize("lab", BASE_LABS)
def test_security_roles(lab):
    cfg = load(lab)
    dc_of = {d["dc"]: name for name, d in cfg["domains"].items()}
    for host, v in cfg["hosts"].items():
        security = v.get("security") or []
        assert "enable_run_as_ppl" in security, host
        assert not EXCLUDED_SECURITY & set(security), host
        if v["type"] == "server":
            assert "asr" in security
            assert [r["ruleid"] for r in v["security_vars"]["asr"].values()] == [ASR_LSASS]
        else:
            assert "asr" not in security
        if host in dc_of:
            assert "account_is_sensitive" in security
            accounts = {a["account"] for a in v["security_vars"]["account_is_sensitive"].values()}
            assert accounts == T0[dc_of[host]]
        else:
            assert "account_is_sensitive" not in security


@pytest.mark.parametrize("lab", BASE_LABS)
def test_playbook_order(lab):
    pb = yaml.safe_load(open("playbooks.yml"))[lab]
    assert pb[-3:] == ["security.yml", "reboot.yml", "hardening.yml"]
    assert "ad-gmsa.yml" not in pb


@pytest.mark.parametrize("lab", BASE_LABS)
def test_webdav_group_empty(lab):
    assert _inventory_group(lab, "webdav") == []


ALWAYS_PRESENT = {"all", "localhost", "domain", "dc"}


def _play_groups(playbook):
    groups = set()
    for play in yaml.safe_load(open(f"ansible/{playbook}")) or []:
        if "hosts" not in play:
            continue
        for pattern in str(play["hosts"]).replace(":", ",").split(","):
            groups.add(pattern.strip().lstrip("!&"))
    return groups


@pytest.mark.parametrize("lab", BASE_LABS)
def test_no_playbook_targets_only_empty_groups(lab):
    for playbook in yaml.safe_load(open("playbooks.yml"))[lab]:
        groups = _play_groups(playbook)
        if not groups or groups & ALWAYS_PRESENT:
            continue
        assert any(_inventory_group(lab, g) for g in groups), f"{playbook} targets only empty groups {groups}"
