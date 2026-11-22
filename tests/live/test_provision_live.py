"""Run by hand on the VMware host with win2022 and win2025 templates, 20 GB of free RAM and no lab
deployed: pytest -m live -k provision -s. It takes about 40 minutes."""
import re

import pytest

from goad.cli import main
from goad.host.runner import Runner
from goad.lab import lifecycle
from goad.lab.context import open_lab
from goad.settings import load_settings
from goad.state import load_state, log_dir
from goad.templates.store import TemplateStore
from goad.vmware.vmrun import Vmrun
from tests.live.helpers import PASSWORD, psrp, wait_logon

pytestmark = pytest.mark.live

DC01, DC02, DC03, SRV02, SRV03 = (f'192.168.56.{octet}' for octet in (10, 11, 12, 22, 23))


def laps_row(settings, runner) -> str:
    rows = [r for r in lifecycle.creds(open_lab(settings, runner)) if r.scope == 'local srv03 (LAPS)']
    assert len(rows) == 1, rows
    password = rows[0].password
    assert password != PASSWORD and not password.startswith('unavailable'), password
    assert psrp(SRV03, '.\\Administrator', 'hostname', password=password).lower() == 'braavos'
    return password


def wait_logons() -> None:
    """Deploy and reset return when WinRM listens; AD DS on a DC accepts logons later."""
    for ip in (DC01, DC02, DC03, SRV02):
        print(f'logon {ip} after {wait_logon(ip, "Administrator"):.0f} s')


def check_content() -> None:
    assert psrp(DC01, 'Administrator',
                '(Get-ADUser cersei.lannister -Properties AccountNotDelegated).AccountNotDelegated') == 'True'
    # Get-ADGroupMember resolves the foreign member through the trust, which fails over PSRP (double hop):
    # read the member DNs instead. A member of another forest is a foreign security principal named by its SID.
    sid = psrp(DC03, 'Administrator', '(Get-ADUser daenerys.targaryen).SID.Value')
    members = psrp(DC01, 'Administrator', '(Get-ADGroup AcrossTheNarrowSea -Properties member).member').splitlines()
    assert any(m.startswith(f'CN={sid},CN=ForeignSecurityPrincipals,') for m in members), (sid, members)
    assert psrp(DC01, 'Administrator', '(Get-ADDomain).DomainMode') == 'Windows2016Domain'
    trust = psrp(DC03, 'Administrator',
                 '$t = Get-ADTrust -Identity sevenkingdoms.local; "$($t.Direction) $($t.ForestTransitive)"')
    assert trust == 'BiDirectional True', trust
    addresses = psrp(SRV02, 'Administrator',
                     '(Resolve-DnsName kingslanding.sevenkingdoms.local -Type A).IPAddress').splitlines()
    assert addresses == [DC01], addresses
    binding = psrp(DC02, 'Administrator', '(Get-ItemProperty HKLM:\\SYSTEM\\CurrentControlSet\\Services\\NTDS\\'
                   'Parameters -Name LdapEnforceChannelBinding).LdapEnforceChannelBinding')
    assert binding == '2', binding


def check_idempotent(settings) -> None:
    logs = sorted(log_dir(settings).glob('provision-*.log'))
    text = logs[-1].read_text(errors='replace')
    recap = text.split('PLAY RECAP', 1)[1]
    hosts = [line for line in recap.splitlines() if re.search(r'\bok=\d+', line)]
    assert hosts, f'no PLAY RECAP host lines in {logs[-1]}'
    assert all(re.search(r'\bchanged=0\b', line) for line in hosts), hosts
    assert re.search(r'^forest\b.*\d+\.\d+s', text, re.MULTILINE), f'no profile_roles line for forest in {logs[-1]}'


def test_provision_2forests():
    settings, runner = load_settings(), Runner()
    store = TemplateStore(settings, Vmrun(runner, settings))
    for os_name in ('win2022', 'win2025'):
        if store.latest(os_name) is None:
            pytest.skip(f'no {os_name} template built')
    if load_state(settings) is not None:
        pytest.fail('a lab is already deployed: run goad lab destroy first')
    try:
        assert main(['lab', 'deploy', '2forests']) == 0
        wait_logons()
        check_content()
        laps_row(settings, runner)
        assert main(['lab', 'provision']) == 0
        check_idempotent(settings)
        assert main(['lab', 'reset']) == 0
        wait_logons()
        laps_row(settings, runner)
    except BaseException:
        main(['lab', 'destroy', '--yes'])   # best effort: the original failure is the one reported
        raise
    assert main(['lab', 'destroy', '--yes']) == 0
