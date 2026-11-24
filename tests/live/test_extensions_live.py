"""Run by hand on the VMware host with the 2forests lab deployed on its snapshot base, with no scenarios and no
extensions: pytest -m live tests/live/test_extensions_live.py -s. Each test adds what it checks and removes it again,
so a passing test leaves the lab as it found it. A failing test leaves the lab half changed: its message says how to
get back (goad extension remove NAME --yes, or goad lab reset ext-iis first when scenarios are on)."""
import contextlib
import time
import urllib.error
import urllib.request
from typing import Dict, Tuple

import pytest
import yaml

from goad.cli import main
from goad.lab import scenario_ops
from goad.lab.definition import parse_lab
from goad.state import load_state, working_lab_path
from goad.settings import load_settings
from goad.templates.smoke import wait_port
from tests.live.helpers import psrp, ssh, wait_logon
from tests.live.test_scenarios_live import _logins, _wait_all

pytestmark = pytest.mark.live

SQL_BASE = "(Get-Service 'MSSQL$SQLEXPRESS').Status"


def _require_clean_2forests():
    settings = load_settings()
    state = load_state(settings)
    if state is None or not state.deployed:
        pytest.skip('no deployed lab')
    if state.lab != '2forests':
        pytest.skip(f'deployed lab is {state.lab}, not 2forests')
    if state.current != 'base':
        pytest.skip(f'current snapshot is {state.current!r}, not base')
    path = working_lab_path(settings)
    raw = yaml.safe_load(path.read_text()) if path.is_file() else None
    if isinstance(raw, dict) and (raw.get('extensions') or raw.get('scenarios')):
        pytest.skip('lab has scenarios or extensions: goad lab reset base first')
    return settings, state


@contextlib.contextmanager
def recovery(hint: str):
    """Add the commands that put the lab back to the message of any failure."""
    try:
        yield
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        raise AssertionError(f'{type(e).__name__}: {e}\nlab left half changed. recover with: {hint}') from e


def _goad(*args: str) -> None:
    assert main(list(args)) == 0, f'goad {" ".join(args)} failed'


def _logins_now(settings) -> Dict[str, Tuple[str, str]]:
    """host key -> (ip, domain admin login), extension hosts included: those of the base lab.yml are in their
    own domain, the others (ws01, lx01, srv01 ...) are in sevenkingdoms.local."""
    state = load_state(settings)
    lab = parse_lab(state.snapshot('base').lab_yml, 'base lab.yml')
    logins = {}
    for name, host in state.hosts.items():
        domain = lab.domains[lab.hosts[name].domain].netbios if name in lab.hosts else 'SEVENKINGDOMS'
        logins[name] = (host.ip, f'{domain}\\Administrator')
    return logins


def _sql(logins, host: str, query: str) -> str:
    ip, user = logins[host]
    ps = ("$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine'); "
          f"SqlCmd -S 127.0.0.1,1433 -E -h -1 -W -Q \"SET NOCOUNT ON; {query}\"")
    return psrp(ip, user, ps)


def _service(logins, host: str, expr: str) -> str:
    return psrp(*logins[host], expr)


def _http(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _wait_http(url: str, timeout: float = 300) -> int:
    start = time.monotonic()
    while True:
        try:
            return _http(url)
        except OSError:
            if time.monotonic() - start >= timeout:
                raise
            time.sleep(10)


MSSQL_PROBES = {
    'mssql-sysadmin': ('srv02', "SELECT IS_SRVROLEMEMBER('sysadmin', 'NORTH\\scn-sql-admin')", '1'),
    'mssql-impersonate-login': ('srv02', "SELECT COUNT(*) FROM sys.server_permissions p JOIN sys.server_principals g "
                                         "ON p.grantee_principal_id = g.principal_id JOIN sys.server_principals t "
                                         "ON p.major_id = t.principal_id WHERE p.permission_name = 'IMPERSONATE' "
                                         "AND g.name = 'NORTH\\scn-sql-imp' AND t.name = 'sa'", '1'),
    'mssql-impersonate-user': ('srv02', "SELECT COUNT(*) FROM msdb.sys.database_permissions p JOIN "
                                        "msdb.sys.database_principals g ON p.grantee_principal_id = g.principal_id "
                                        "JOIN msdb.sys.database_principals t ON p.major_id = t.principal_id "
                                        "WHERE p.permission_name = 'IMPERSONATE' AND g.name = 'NORTH\\scn-sql-dbo' "
                                        "AND t.name = 'dbo'", '1'),
    'mssql-linked': ('srv02', "SELECT COUNT(*) FROM sys.servers s JOIN sys.linked_logins l ON s.server_id = "
                              "l.server_id JOIN sys.server_principals p ON l.local_principal_id = p.principal_id "
                              "WHERE s.name = 'BRAAVOS' AND s.is_linked = 1 AND s.data_source = 'braavos.essos.local' "
                              "AND p.name = 'NORTH\\scn-sql-link' AND l.remote_name = 'sa'", '1'),
}
# Values of a probe on a lab without its scenario.
ABSENT = {'mssql-sysadmin': '0', 'mssql-impersonate-login': '0', 'mssql-impersonate-user': '0', 'mssql-linked': '0'}


def _read(logins, name: str) -> str:
    host, query, _ = MSSQL_PROBES[name]
    return _sql(logins, host, query).splitlines()[0].strip()


def _wait_ports(logins) -> None:
    for host in ('srv02', 'srv03'):
        wait_port(logins[host][0], 5985)
    _wait_all({h: v for h, v in logins.items() if h in ('dc01', 'dc02', 'srv02')})


def test_mssql_iis_and_scenarios_live():
    settings, _ = _require_clean_2forests()
    logins = _logins_now(settings)
    hint = ('goad lab reset ext-iis (when it exists), goad extension remove iis --yes, '
            'goad extension remove mssql --yes')
    with recovery(hint):
        _goad('extension', 'add', 'mssql')
        _goad('extension', 'add', 'iis')
        logins = _logins_now(settings)
        _wait_ports(logins)
        for host in ('srv02', 'srv03'):
            assert _service(logins, host, SQL_BASE) == 'Running', host
        srv02 = logins['srv02'][0]
        assert _wait_http(f'http://{srv02}/') == 200
        names = list(MSSQL_PROBES) + ['iis-upload']
        targets = {name: scenario_ops.add_entry(load_text(settings), name, None)[1] for name in names}
        for name in names:
            _goad('scenario', 'enable', name)
        _wait_ports(logins)
        for name, (_, _, enabled) in MSSQL_PROBES.items():
            assert _read(logins, name) == enabled, name
        assert _http(f'http://{srv02}/Default.aspx') == 200
        # reset base must be refused while extensions are on
        assert main(['lab', 'reset', 'base']) != 0
        # disable one scenario: reset to ext-iis, the others replayed
        _goad('scenario', 'disable', 'mssql-sysadmin', '--target', targets['mssql-sysadmin'], '--yes')
        _wait_ports(logins)
        assert _read(logins, 'mssql-sysadmin') == ABSENT['mssql-sysadmin']
        for name in ('mssql-impersonate-login', 'mssql-impersonate-user', 'mssql-linked'):
            assert _read(logins, name) == MSSQL_PROBES[name][2], name
        assert _http(f'http://{srv02}/Default.aspx') == 200
        # drop the rest of the scenarios by returning to ext-iis, then remove the extensions
        _goad('lab', 'reset', 'ext-iis')
        _wait_ports(logins)
        _goad('extension', 'remove', 'iis', '--yes')
        _goad('extension', 'remove', 'mssql', '--yes')
        _wait_all({h: v for h, v in logins.items() if h in ('dc01', 'dc02', 'srv02')})
        _goad('lab', 'reset', 'base')
        _wait_all({h: v for h, v in _logins(load_state(settings)).items()})
        assert load_state(settings).current == 'base'
        with pytest.raises(AssertionError):
            _service(_logins(load_state(settings)), 'srv02', SQL_BASE)   # no SQL service back on base
        raw = yaml.safe_load(load_text(settings))
        assert not raw.get('extensions') and not raw.get('scenarios')


def load_text(settings) -> str:
    return working_lab_path(settings).read_text()


def _add(name: str, hint_extra: str = ''):
    return recovery(f'goad extension remove {name} --yes{hint_extra}')


def _remove(settings, name: str) -> None:
    _goad('extension', 'remove', name, '--yes')
    state = load_state(settings)
    assert state.current == 'base', f'after removing {name} lab is on {state.current!r}, not base'
    raw = yaml.safe_load(load_text(settings))
    assert not raw.get('extensions'), raw.get('extensions')


def _kali_template() -> None:
    from goad.host.runner import Runner
    from goad.templates.store import TemplateStore
    from goad.vmware.vmrun import Vmrun
    settings = load_settings()
    store = TemplateStore(settings, Vmrun(Runner(), settings))
    if store.latest('kali') is None:
        with recovery('goad template import kali; goad template test kali'):
            _goad('template', 'import', 'kali')
            _goad('template', 'test', 'kali')


def _vm_ip(settings, host: str) -> str:
    return load_state(settings).hosts[host].ip


def test_vm_extensions_live():
    settings, _ = _require_clean_2forests()
    _kali_template()

    with _add('ws01'):
        _goad('extension', 'add', 'ws01')
        ip = _vm_ip(settings, 'ws01')
        wait_logon(ip, 'SEVENKINGDOMS\\Administrator')
        assert psrp(ip, 'SEVENKINGDOMS\\Administrator', '(Get-CimInstance Win32_ComputerSystem).Domain') \
            == 'sevenkingdoms.local'
        assert psrp(ip, 'SEVENKINGDOMS\\Administrator', '(Get-CimInstance Win32_ComputerSystem).PartOfDomain') == 'True'
        _remove(settings, 'ws01')

    with _add('lx01'):
        _goad('extension', 'add', 'lx01')
        ip = _vm_ip(settings, 'lx01')
        wait_port(ip, 22)
        assert 'sevenkingdoms.local' in ssh(ip, 'realm list')
        _remove(settings, 'lx01')

    with _add('kali'):
        _goad('extension', 'add', 'kali')
        ip = _vm_ip(settings, 'kali')
        wait_port(ip, 22)
        assert ssh(ip, 'whoami') == 'goad'
        # NAT internet: a known risk is the NAT NIC under NetworkManager
        assert 'default' in ssh(ip, 'ip route'), 'kali has no default route'
        ssh(ip, 'curl -sI --max-time 20 http://http.kali.org')
        _remove(settings, 'kali')

    with _add('elk'):
        _goad('extension', 'add', 'elk')
        logins = _logins_now(settings)
        wait_port(_vm_ip(settings, 'elk'), 5601, timeout=600)
        assert _wait_http(f'http://{_vm_ip(settings, "elk")}:5601/') in (200, 302, 401)
        assert _service(logins, 'dc01', "(Get-Service winlogbeat).Status") == 'Running'
        _remove(settings, 'elk')

    with _add('wazuh'):
        _goad('extension', 'add', 'wazuh')
        logins = _logins_now(settings)
        wait_port(_vm_ip(settings, 'wazuh'), 443, timeout=600)
        assert _service(logins, 'dc01', "(Get-Service WazuhSvc).Status") == 'Running'
        _remove(settings, 'wazuh')

    with _add('exchange'):
        _goad('extension', 'add', 'exchange')
        logins = _logins_now(settings)
        wait_logon(*logins['srv01'])
        out = psrp(*logins['srv01'], "Add-PSSnapin Microsoft.Exchange.Management.PowerShell.SnapIn; "
                                     "(Get-ExchangeServer).Name")
        assert out, 'Get-ExchangeServer returned no server'
        _remove(settings, 'exchange')
