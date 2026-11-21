"""Remote actions on a deployed Windows guest."""
from goad import GoadError

# The template's setup account: packer/windows/windows.pkr.hcl local.setup_user
SETUP_USER = 'goad-setup'


def remove_setup_account(ip: str, password: str) -> None:
    from pypsrp.client import Client
    script = (f'if (Get-LocalUser -Name {SETUP_USER} -ErrorAction SilentlyContinue) '
              f'{{ Remove-LocalUser -Name {SETUP_USER} }}')
    _, _, had_errors = Client(ip, username='Administrator', password=password, ssl=False, auth='ntlm',
                              cert_validation=False).execute_ps(script)
    if had_errors:
        raise GoadError(f'cannot remove account {SETUP_USER} on {ip}')


def laps_password(dc_ip: str, password: str, hostname: str) -> str:
    from pypsrp.client import Client
    quoted = hostname.replace("'", "''")
    script = f"(Get-LapsADPassword -Identity '{quoted}' -AsPlainText).Password"
    try:
        output, _, had_errors = Client(dc_ip, username='Administrator', password=password, ssl=False,
                                       auth='ntlm', cert_validation=False).execute_ps(script)
    except Exception as exc:
        raise GoadError(f'no LAPS password for {hostname}') from exc
    result = str(output).strip()
    if had_errors or not result:
        raise GoadError(f'no LAPS password for {hostname}')
    return result
