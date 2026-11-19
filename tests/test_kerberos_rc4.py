from pathlib import Path

import yaml

TASK = Path(__file__).resolve().parent.parent / "ansible/roles/base_setting/tasks/kerberos_rc4.yml"


def _trust_script():
    tasks = yaml.safe_load(TASK.read_text())
    task = next(t for t in tasks if "trust" in t["name"].lower())
    return task["ansible.windows.win_powershell"]["script"]


def test_trust_enctypes_written_through_lsa_not_ldap():
    # AD refuses LDAP writes of msDS-SupportedEncryptionTypes on trustedDomain objects
    # ("Illegal modify operation"); ksetup /setenctypeattr goes through LSA.
    script = _trust_script()
    assert "Set-ADObject" not in script
    assert "ksetup /setenctypeattr" in script
    assert "$LASTEXITCODE" in script


def test_trust_enctypes_names_match_wanted_values():
    script = _trust_script()
    assert "AES128-CTS-HMAC-SHA1-96" in script
    assert "AES256-CTS-HMAC-SHA1-96" in script
    assert "RC4-HMAC-MD5" in script
