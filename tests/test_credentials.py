import json
import os

import yaml

from goad.credentials import collect_credentials

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LAB = {
    "hosts": {
        "dc01": {"hostname": "kingslanding", "domain": "sevenkingdoms.local", "local_admin_password": "Aa1234567890!"},
        "srv02": {"hostname": "castelblack", "domain": "sevenkingdoms.local", "local_admin_password": "Aa1234567890!",
                  "mssql": {"sa_password": "Sup1_sa_P@ssw0rd!"}},
    },
    "domains": {
        "sevenkingdoms.local": {
            "netbios_name": "SEVENKINGDOMS",
            "domain_password": "Aa1234567890!",
            "users": {"jon.snow": {"password": "Aa1234567890!"}, "arya.stark": {"password": "Needle"}},
        }
    },
}


def test_domain_admin_and_users_listed():
    rows = collect_credentials(LAB, [], None)
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\Administrator", "Aa1234567890!", "domain admin") in rows
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\arya.stark", "Needle", "user") in rows
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\jon.snow", "Aa1234567890!", "user") in rows


def test_local_admin_and_mssql_sa_listed():
    rows = collect_credentials(LAB, [], None)
    assert ("dc01 (kingslanding)", ".\\Administrator", "Aa1234567890!", "local admin") in rows
    assert ("srv02 (castelblack)", "sa", "Sup1_sa_P@ssw0rd!", "mssql") in rows


def test_enabled_scenario_accounts_listed():
    enabled = [("kerberoast", "dc01")]
    rows = collect_credentials(LAB, enabled, os.path.join(ROOT, "scenarios"))
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\svc_kerb", "Aa1234567890!", "scenario kerberoast") in rows


def test_scenario_without_account_or_unknown_is_ignored():
    enabled = [("esc8", "dc01"), ("does-not-exist", "dc01")]
    rows = collect_credentials(LAB, enabled, os.path.join(ROOT, "scenarios"))
    assert not any(r[3].startswith("scenario") for r in rows)


def test_missing_sections_do_not_crash():
    assert collect_credentials({}, [], None) == []


EXTENSIONS = os.path.join(ROOT, "extensions")


def test_enabled_extension_data_accounts_listed():
    rows = collect_credentials(LAB, [], None, extensions_path=EXTENSIONS, enabled_extensions=["lx01", "exchange"])
    assert not any(r[0] == "lx01 (dragonstone)" for r in rows)  # linux: no Administrator account
    assert ("srv01 (the-eyrie)", ".\\Administrator", "Aa1234567890!", "local admin") in rows
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\lysa.arryn", "Aa1234567890!", "user") in rows
    # the lab users stay listed next to the extension ones
    assert ("sevenkingdoms.local", "SEVENKINGDOMS\\arya.stark", "Needle", "user") in rows


def test_extension_data_does_not_change_the_given_lab():
    collect_credentials(LAB, [], None, extensions_path=EXTENSIONS, enabled_extensions=["lx01"])
    assert "lx01" not in LAB["hosts"]


def test_enabled_extension_service_accounts_listed():
    rows = collect_credentials(LAB, [], None, extensions_path=EXTENSIONS,
                               enabled_extensions=["elk", "wazuh"], ip_range="192.168.56")
    assert ("elk (http://192.168.56.50:5601)", "elastic", "Aa1234567890!", "kibana") in rows
    assert ("wazuh (https://192.168.56.51)", "admin", "Aa1234567890!", "wazuh dashboard") in rows


def test_disabled_or_unknown_extensions_add_nothing():
    base = collect_credentials(LAB, [], None)
    assert collect_credentials(LAB, [], None, extensions_path=EXTENSIONS, enabled_extensions=["nope"]) == base
    assert collect_credentials(LAB, [], None, extensions_path=EXTENSIONS, enabled_extensions=[]) == base


def _role_default(path, key):
    with open(os.path.join(EXTENSIONS, path)) as f:
        return yaml.safe_load(f)[key]


def _declared_password(extension, account):
    with open(os.path.join(EXTENSIONS, extension, "extension.json")) as f:
        creds = json.load(f)["credentials"]
    return next(c["password"] for c in creds if c["account"] == account)


def test_extension_declared_passwords_match_the_role_defaults():
    # show_credentials reads extension.json, the playbooks read the role defaults: keep them equal
    assert _declared_password("elk", "elastic") == _role_default("elk/ansible/roles/elk/defaults/main.yml", "elk_elastic_password")
    assert _declared_password("elk", "elastic") == _role_default("elk/ansible/roles/logs_windows/defaults/main.yml", "elk_elastic_password")
    assert _declared_password("wazuh", "admin") == _role_default("wazuh/ansible/roles/wazuh_manager/defaults/main.yml", "wazuh_admin_password")
