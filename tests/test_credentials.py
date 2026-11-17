import os

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
