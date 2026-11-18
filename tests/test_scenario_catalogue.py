import json
import re
from pathlib import Path

import pytest
import yaml

from goad.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
BASE_LABS = ["GOAD-Mini-Base", "GOAD-Light-Base", "GOAD-Base"]
MS = ["member_server"]


def setting(target, requires, key, value):
    return {"type": "setting", "target": target, "requires": requires, "depends": [], "touches": [key],
            "setting": (key, value)}


def obj(target="", requires=None, depends=None):
    return {"type": "object", "target": target, "requires": requires or [], "depends": depends or [], "touches": []}


CATALOGUE = {
    "smb-signing-off": setting("member_server", MS, "smb.signing", "optional"),
    "ntlm-downgrade": setting("", [], "ntlm.lmcompat", 2),
    "ldap-signing-off": setting("", [], "ldap.signing", "none"),
    "ldap-cbt-off": setting("", [], "ldap.channel_binding", "never"),
    "printerbug": setting("", [], "dc.spooler", "enabled"),
    "esc10-case1": setting("", ["adcs"], "dc.strong_cert_binding", 0),
    "esc10-case2": setting("", ["adcs"], "dc.cert_mapping", "0x4"),
    "esc6": setting("adcs", ["adcs"], "adcs.editf_san", "on"),
    "esc11": setting("adcs", ["adcs"], "adcs.enforce_encrypt", "off"),
    "rc4": setting("", [], "kerberos.rc4", "enabled"),
    "mdns": setting("member_server", MS, "net.mdns", "enabled"),
    "defender-off": setting("member_server", MS, "defender.realtime", "off"),
    "firewall-off": setting("member_server", MS, "firewall.state", "off"),
    "maq": setting("", [], "dc.maq", 10),
    "smbv1": setting("member_server", MS, "smb.v1", "enabled"),
    "credssp": setting("member_server", MS, "winrm.credssp", "server"),
    "sid-history": setting("forest_trust", ["forest_trust"], "trust.sid_history", "enabled"),
    "webdav": setting("member_server", MS, "net.webclient", "present"),
    # ADCS
    "esc2": obj("adcs", ["adcs"]),
    "esc3": obj("adcs", ["adcs"]),
    "esc4": obj("adcs", ["adcs"]),
    "esc7": obj("adcs", ["adcs"]),
    "esc9": obj("adcs", ["adcs"], ["esc10-case1"]),
    "esc13": obj("adcs", ["adcs"]),
    "esc15": obj("adcs", ["adcs"]),
    # ACL
    "acl-forcechangepassword": obj(),
    "acl-genericwrite-user": obj(),
    "acl-writedacl-user": obj(),
    "acl-self-membership": obj(),
    "acl-addmember": obj(),
    "acl-writeowner": obj(),
    "acl-genericall-user": obj(),
    "acl-genericall-computer": obj(),
    "acl-genericall-group": obj("member_server", MS),
    "acl-adminsdholder": obj(),
    "acl-writedacl-ou": obj(),
    "acl-writeproperty": obj(),
    "anonymous-rpc": obj(),
    "gpo-abuse": obj(),
    "foreign-group-acl": obj("forest_trust", ["forest_trust"]),
    "local-admin": obj("member_server", MS),
    # delegation
    "constrained-deleg-any": obj(),
    "constrained-deleg-kerb": obj("member_server", MS),
    "unconstrained-computer": obj("member_server", MS),
    "unconstrained-user": obj(),
    "rbcd": obj("member_server", MS, ["maq"]),
    "writespn": obj(),
    # MSSQL / IIS
    "mssql-impersonate-login": obj("mssql", ["mssql"]),
    "mssql-impersonate-user": obj("mssql", ["mssql"]),
    "mssql-sysadmin": obj("mssql", ["mssql"]),
    "mssql-linked": obj("mssql_link", ["mssql_link"]),
    "iis-upload": obj("iis", ["iis"]),
}

SETTINGS = [n for n, c in CATALOGUE.items() if c["type"] == "setting"]
PACKAGES = sorted(p.name for p in (ROOT / "scenarios").iterdir() if (p / "scenario.json").exists())


def load(name):
    return Scenario.from_file(name, str(ROOT / "scenarios" / name / "scenario.json"))


def vars_of(name):
    path = ROOT / "scenarios" / name / "data" / "vars.yml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def lab(name):
    return json.load(open(ROOT / "ad" / name / "data" / "config.json"))["lab"]


def leaves(node, top=None):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, top or k)
    elif isinstance(node, list):
        for v in node:
            yield from leaves(v, top)
    else:
        yield top, node


@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_catalogue_package(name):
    s = load(name)
    want = CATALOGUE[name]
    assert (s.type, s.target, s.requires, s.depends, s.touches) == \
        (want["type"], want["target"], want["requires"], want["depends"], want["touches"])


@pytest.mark.parametrize("name", SETTINGS)
def test_setting_vars(name):
    key, value = CATALOGUE[name]["setting"]
    assert vars_of(name)["touched_settings"] == [{"key": key, "vulnerable_value": value}]


@pytest.mark.parametrize("name", SETTINGS)
def test_setting_uninstall_restores_baseline(name):
    text = (ROOT / "scenarios" / name / "ansible" / "uninstall.yml").read_text()
    assert 'setting_value: "{{ lab.base_settings[scenario_target][scenario_setting.key] }}"' in text


@pytest.mark.parametrize("lab_name", BASE_LABS)
def test_setting_baseline_exists_for_every_candidate(lab_name):
    cfg = lab(lab_name)
    caps = cfg["capabilities"]
    dcs = [h for h, v in cfg["hosts"].items() if v["type"] == "dc"]
    for name in PACKAGES:
        s = load(name)
        if s.type != "setting" or any(r not in caps for r in s.requires):
            continue
        for host in (caps.get(s.target) or []) if s.target else dcs:
            for key in s.touches:
                assert key in cfg["base_settings"][host], f"{name}: {key} missing on {lab_name}/{host}"


@pytest.mark.parametrize("name", PACKAGES)
def test_scn_names_fit_sam(name):
    for _, value in leaves(vars_of(name)):
        if isinstance(value, str) and value.startswith("scn-"):
            assert len(value) <= 20, value


@pytest.mark.parametrize("name", PACKAGES)
def test_uninstall_references_every_scn_name(name):
    text = (ROOT / "scenarios" / name / "ansible" / "uninstall.yml").read_text()
    for top, value in leaves(vars_of(name)):
        if isinstance(value, str) and (value.startswith("scn-") or top in ("template", "templates")):
            assert value in text or re.search(r"\b%s\b" % re.escape(top), text), f"{name}: {top}={value}"


@pytest.mark.parametrize("name", ["maq"])
def test_uninstall_deletes_quota_computers(name):
    text = (ROOT / "scenarios" / name / "ansible" / "uninstall.yml").read_text()
    assert "mS-DS-CreatorSID" in text and "Remove-ADComputer" in text


def _includes(node):
    if isinstance(node, dict):
        if any(k.split(".")[-1] == "include_role" for k in node):
            yield node
        for v in node.values():
            yield from _includes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _includes(v)


@pytest.mark.parametrize("name", PACKAGES)
def test_include_vars_not_self_referential(name):
    # vars: {x: "{{ x }}"} on an include is a recursive template loop at runtime
    for pb in ("install.yml", "uninstall.yml"):
        for task in _includes(yaml.safe_load((ROOT / "scenarios" / name / "ansible" / pb).read_text())):
            for key, value in (task.get("vars") or {}).items():
                assert not re.fullmatch(r"\{\{\s*%s\s*\}\}" % re.escape(key), str(value)), f"{pb}: {key}"


AD_MARKERS = re.compile(r"Import-Module ActiveDirectory|-AD[A-Z]|\bAD:|\[ADSI\]|Get-GP|New-GP|Remove-GP")


def _tasks(node):
    if isinstance(node, dict):
        if "name" in node and any(k.startswith("ansible.") for k in node):
            yield node
        for v in node.values():
            yield from _tasks(v)
    elif isinstance(node, list):
        for v in node:
            yield from _tasks(v)


def _non_dc_targets():
    found = set()
    for lab_name in BASE_LABS:
        cfg = lab(lab_name)
        dcs = {h for h, v in cfg["hosts"].items() if v["type"] == "dc"}
        for name in PACKAGES:
            s = load(name)
            if s.type == "object" and s.target and set(cfg["capabilities"].get(s.target, [])) - dcs:
                found.add(name)
    return sorted(found)


@pytest.mark.parametrize("name", _non_dc_targets())
def test_ad_tasks_delegate_to_dc(name):
    # AD work must run on the domain DC when the target can be a member server
    for pb in ("install.yml", "uninstall.yml"):
        for task in _tasks(yaml.safe_load((ROOT / "scenarios" / name / "ansible" / pb).read_text())):
            body = json.dumps(task)
            if AD_MARKERS.search(body) and not any(k.endswith("include_role") for k in task):
                assert task.get("delegate_to") == "{{ dc }}", f"{pb}: {task['name']}"


def test_docs_list_every_scenario():
    text = (ROOT / "docs" / "mkdocs" / "docs" / "scenarios.md").read_text()
    section = text.split("## Provided scenarios", 1)[1].split("\n## ", 1)[0]
    missing = [n for n in PACKAGES if f"| `{n}` |" not in section]
    assert not missing, missing
