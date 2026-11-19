"""The VM-less service extensions (mssql, iis) that put services back on the Base member servers."""
import json
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from goad.extension import Extension

ROOT = Path(__file__).resolve().parent.parent
LABS = ["GOAD-Base", "GOAD-Light-Base"]
SERVICE_EXTENSIONS = {"mssql": {"mssql", "mssql_ssms"}}


def info(name):
    return json.loads((ROOT / "extensions" / name / "extension.json").read_text())


def inventory_groups(name, lab_name):
    """Render the extension inventory for lab_name and return {group: [hosts]} (vars sections excluded)."""
    text = Environment(loader=FileSystemLoader(str(ROOT / "extensions" / name))).get_template("inventory").render(
        lab_name=lab_name, ip_range="192.168.56", provider_name="vmware")
    groups, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line[1:-1]
            groups.setdefault(current, [])
        elif current is not None and ":" not in current:
            groups[current].append(line.split()[0])
    return groups, text


def playbook(name, pb):
    return yaml.safe_load((ROOT / "extensions" / name / "ansible" / pb).read_text())


@pytest.mark.parametrize("name", sorted(SERVICE_EXTENSIONS))
def test_extension_metadata(name):
    data = info(name)
    assert data["machines"] == []
    assert data["compatibility"] == LABS
    assert set(data["capabilities"]) == set(LABS)


@pytest.mark.parametrize("name", sorted(SERVICE_EXTENSIONS))
def test_extension_has_no_providers(name):
    assert not (ROOT / "extensions" / name / "providers").exists()
    assert not (ROOT / "extensions" / name / "data").exists()


@pytest.mark.parametrize("name", sorted(SERVICE_EXTENSIONS))
@pytest.mark.parametrize("lab_name", LABS)
def test_inventory_matches_capabilities(name, lab_name):
    groups, _ = inventory_groups(name, lab_name)
    caps = info(name)["capabilities"][lab_name]
    for group in SERVICE_EXTENSIONS[name] & set(caps):
        assert groups.get(group) == caps[group], group
    assert groups.get("extensions") == []
    lab_hosts = json.loads((ROOT / "ad" / lab_name / "data" / "config.json").read_text())["lab"]["hosts"]
    for hosts in groups.values():
        assert set(hosts) <= set(lab_hosts)


@pytest.mark.parametrize("name", sorted(SERVICE_EXTENSIONS))
def test_extension_loads_with_uninstall(name):
    ext = Extension(name)
    assert ext.has_uninstall()
    assert ext.capabilities_for("GOAD") == {}


@pytest.mark.parametrize("name", sorted(SERVICE_EXTENSIONS))
@pytest.mark.parametrize("pb", ["install.yml", "uninstall.yml"])
def test_playbooks_parse_and_load_lab_data(name, pb):
    plays = playbook(name, pb)
    assert plays[0]["import_playbook"] == "../../../ansible/data.yml"


def test_mssql_capabilities():
    caps = info("mssql")["capabilities"]
    assert caps["GOAD-Base"] == {"mssql": ["srv02", "srv03"], "mssql_link": ["srv02"]}
    assert caps["GOAD-Light-Base"] == {"mssql": ["srv02"]}
    assert Extension("mssql").capabilities_for("GOAD-Base")["mssql"] == ["srv02", "srv03"]


@pytest.mark.parametrize("lab_name", LABS)
def test_mssql_inventory(lab_name):
    groups, text = inventory_groups("mssql", lab_name)
    assert groups["mssql_ssms"] == ["srv02"]
    assert "mssql_sa_password=Aa1234567890!" in text


def test_mssql_install_has_no_vulns():
    text = (ROOT / "extensions" / "mssql" / "ansible" / "install.yml").read_text()
    assert "mssql_link" not in text
    assert "executeaslogin: {}" in text
    assert "executeasuser: {}" in text
    assert "spn" not in text.lower()


def test_mssql_uninstall_undoes_install():
    text = (ROOT / "extensions" / "mssql" / "ansible" / "uninstall.yml").read_text()
    assert "/ACTION=Uninstall" in text
    assert "/uninstall" in text  # SSMS
    assert 'ad_state: "absent"' in text
    assert "SeServiceLogonRight" in text
    assert "Access for MSSQL (TCP-In)" in text and "Access for MSSQL (UDP-In)" in text
