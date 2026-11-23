"""Run by hand on the VMware host with the 2forests lab deployed and its current snapshot base:
pytest -m live tests/live/test_scenarios_live.py -s. It resets to base at start and end, never destroys.

PROBES maps a scenario name to (host key, PowerShell that prints one value, value when enabled). The host
key is the scenario's default target in 2forests: the first host of the kind in lab.yml order (dc01 for
domain, ca and trust, srv02 for server). Later tasks add entries and call run_step."""
import time
from typing import Dict, List, Tuple

import pytest

from goad.cli import main
from goad.lab import scenario_ops
from goad.settings import load_settings
from goad.state import load_state
from tests.live.helpers import psrp, wait_logon

pytestmark = pytest.mark.live


def _reg(path: str, name: str) -> str:
    return (f"$v = (Get-ItemProperty -Path '{path}' -Name '{name}' -ErrorAction SilentlyContinue).'{name}'; "
            "if ($null -eq $v) { 'absent' } else { $v }")


def _certutil_flag(register: str, flag: str) -> str:
    return f"[bool]((certutil -getreg {register} | Out-String) -match '{flag}')"


LSA = 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Lsa'
NTDS = 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\NTDS\\Parameters'
SID_TRUST = ('((Get-ADObject -Identity "CN=essos.local,CN=System,$((Get-ADDomain).DistinguishedName)" '
             '-Properties trustAttributes).trustAttributes -band 0x40) -ne 0')

PROBES: Dict[str, Tuple[str, str, str]] = {
    'credssp': ('srv02', '(Get-Item WSMan:\\localhost\\Service\\Auth\\CredSSP).Value', 'true'),
    'defender-off': ('srv02', '(Get-MpPreference).DisableRealtimeMonitoring', 'True'),
    'esc10-case1': ('dc01', _reg('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Kdc',
                                 'StrongCertificateBindingEnforcement'), '0'),
    'esc10-case2': ('dc01', _reg('HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecurityProviders\\Schannel',
                                 'CertificateMappingMethods'), '4'),
    'esc11': ('dc01', _certutil_flag('CA\\InterfaceFlags', 'IF_ENFORCEENCRYPTICERTREQUEST'), 'False'),
    'esc6': ('dc01', _certutil_flag('policy\\EditFlags', 'EDITF_ATTRIBUTESUBJECTALTNAME2'), 'True'),
    'esc8': ('dc01', '(Get-WindowsFeature ADCS-Web-Enrollment).Installed', 'True'),
    'firewall-off': ('srv02', "@(Get-NetFirewallProfile -Name Domain,Private,Public | "
                              "Where-Object { $_.Enabled.ToString() -eq 'True' }).Count", '0'),
    'ldap-cbt-off': ('dc01', _reg(NTDS, 'LdapEnforceChannelBinding'), '0'),
    'ldap-signing-off': ('dc01', _reg(NTDS, 'LDAPServerIntegrity'), '1'),
    'llmnr': ('srv02', _reg('HKLM:\\Software\\Policies\\Microsoft\\Windows NT\\DNSClient', 'EnableMulticast'), '1'),
    'maq': ('dc01', "(Get-ADObject (Get-ADDomain).DistinguishedName -Properties 'ms-DS-MachineAccountQuota')"
                    ".'ms-DS-MachineAccountQuota'", '10'),
    'mdns': ('srv02', _reg('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Dnscache\\Parameters', 'EnableMDNS'), '1'),
    'ntlm-downgrade': ('dc01', _reg(LSA, 'LmCompatibilityLevel'), '2'),
    'printerbug': ('dc01', '(Get-Service Spooler).Status', 'Running'),
    'rc4': ('dc01', _reg('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\\Kerberos\\Parameters',
                         'SupportedEncryptionTypes'), '28'),
    'sid-history': ('dc01', SID_TRUST, 'True'),
    'smb-signing-off': ('srv02', _reg('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\LanmanServer\\Parameters',
                                      'RequireSecuritySignature'), '0'),
    'smbv1': ('srv02', '(Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol).State', 'Enabled'),
    'webdav': ('srv02', '[bool](Get-Service WebClient -ErrorAction SilentlyContinue)', 'True'),
}

SETTING_SCENARIOS = list(PROBES)


def _require_2forests_on_base(settings):
    state = load_state(settings)
    if state is None or not state.deployed:
        pytest.skip('no deployed lab')
    if state.lab != '2forests':
        pytest.skip(f'deployed lab is {state.lab}, not 2forests')
    if state.current != 'base':
        pytest.skip(f'current snapshot is {state.current!r}, not base')
    return state


def _reset_base(settings) -> None:
    assert main(['lab', 'reset', 'base']) == 0
    state = load_state(settings)
    for key, host in state.hosts.items():
        wait_logon(host.ip, 'Administrator')


def _read(ips: Dict[str, str], name: str) -> str:
    host, script, _ = PROBES[name]
    return psrp(ips[host], 'Administrator', script)


def run_step(names: List[str]) -> None:
    """Enable every name on its default target, assert every probe, disable the middle name and assert its
    probe is back to the base value (read before enabling) and the others still match, reset to base."""
    settings = load_settings()
    state = _require_2forests_on_base(settings)
    ips = {key: host.ip for key, host in state.hosts.items()}
    base_text = state.snapshot('base').lab_yml
    targets = {name: scenario_ops.add_entry(base_text, name, None)[1] for name in names}
    for name in names:
        assert targets[name] == PROBES[name][0], f'{name}: default target {targets[name]}, probe host {PROBES[name][0]}'
    middle = names[len(names) // 2]
    try:
        _reset_base(settings)
        base = {name: _read(ips, name) for name in names}
        assert base[middle] != PROBES[middle][2], f'{middle}: base value {base[middle]!r} already the enabled value'
        start = time.monotonic()
        for name in names:
            assert main(['scenario', 'enable', name]) == 0
        print(f'enable {len(names)} scenarios: {time.monotonic() - start:.0f} s')
        for name in names:
            assert _read(ips, name) == PROBES[name][2], name
        start = time.monotonic()
        assert main(['scenario', 'disable', middle, '--target', targets[middle], '--yes']) == 0
        print(f'disable {middle}: {time.monotonic() - start:.0f} s')
        for host in ips.values():
            wait_logon(host, 'Administrator')
        assert _read(ips, middle) == base[middle], middle
        for name in names:
            if name != middle:
                assert _read(ips, name) == PROBES[name][2], name
    finally:
        _reset_base(settings)


def test_setting_scenarios_live():
    run_step(SETTING_SCENARIOS)
