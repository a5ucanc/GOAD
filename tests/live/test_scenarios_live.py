"""Run by hand on the VMware host with the 2forests lab deployed and its current snapshot base:
pytest -m live tests/live/test_scenarios_live.py -s. It resets to base at start and end, never destroys.

PROBES maps a scenario name to (host key the probe runs on, PowerShell that prints one value, value when enabled). The host
key is the host the probe runs on, which need not be the target: AD objects of a member server are read on
its domain DC (dc02 for srv02). Default targets in 2forests: dc01 for domain, ca and trust, srv02 for server. Later tasks add entries and call run_step."""
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


def _ad_user(name: str, expr: str) -> str:
    return (f"$u = Get-ADUser -LDAPFilter '(sAMAccountName={name})' -Properties servicePrincipalName, "
            "DoesNotRequirePreAuth, TrustedForDelegation, TrustedToAuthForDelegation, 'msDS-AllowedToDelegateTo'; "
            f"if ($null -eq $u) {{ 'absent' }} else {{ {expr} }}")


def _ad_computer(name: str, expr: str) -> str:
    return (f"$c = Get-ADComputer -Identity '{name}' -Properties TrustedForDelegation, 'msDS-AllowedToDelegateTo'; "
            f"{expr}")


EMPTY_GUID = '00000000-0000-0000-0000-000000000000'
MEMBER_GUID = 'bf9679c0-0de6-11d0-a285-00aa003049e2'
SPN_GUID = 'f3a64788-5306-11d1-a9c5-0000f80367c1'
RESET_PWD_GUID = '00299570-246d-11d0-a768-00aa006e0529'


def _ace(who: str, dn: str, rights: str, guid: str = EMPTY_GUID, inherit: str = 'None') -> str:
    """True when an Allow ACE for who (NETBIOS-qualified account) with the rights and object type is on the object.
    dn is a PowerShell expression that gives the object's DN or $null; $null (object absent) reads False."""
    return ("Import-Module ActiveDirectory; $d = (Get-ADDomain).DistinguishedName; "
            f"$dn = {dn}; if (-not $dn) {{ $false }} else {{ try {{ "
            "$r = [DirectoryServices.ActiveDirectoryRights]'" + rights + "'; "
            "[bool]((Get-Acl -Path ('AD:' + $dn) -ErrorAction Stop).Access | Where-Object { "
            f"$_.IdentityReference.Value -like '{who}' -and $_.AccessControlType -eq 'Allow' -and "
            f"($_.ActiveDirectoryRights -band $r) -eq $r -and $_.ObjectType -eq [guid]'{guid}' -and "
            f"$_.InheritanceType -eq '{inherit}' }}) }} catch {{ $false }} }}")


def _sam(name: str) -> str:
    return f"(Get-ADObject -LDAPFilter '(sAMAccountName={name})').DistinguishedName"


def _acl_user(who: str, victim: str, rights: str, guid: str = EMPTY_GUID, inherit: str = 'None') -> str:
    return _ace(f'*\\{who}', _sam(victim), rights, guid, inherit)


GPO_PERMISSION = ("Import-Module GroupPolicy; $p = Get-GPPermission -Name 'scn-gpo-abuse' -TargetName "
                  "'scn-gpo-attacker' -TargetType User -ErrorAction SilentlyContinue; "
                  "if ($null -eq $p) { 'absent' } else { $p.Permission }")


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
    'kerberoast': ('dc01', _ad_user('svc_kerb', "$u.servicePrincipalName -join ','"),
                   'MSSQLSvc/svc-kerb.sevenkingdoms.local:1433'),
    'asrep-roast': ('dc01', _ad_user('asrep_user', '$u.DoesNotRequirePreAuth'), 'True'),
    'unconstrained-user': ('dc01', _ad_user('scn-unconst-svc', '$u.TrustedForDelegation'), 'True'),
    'constrained-deleg-any': ('dc01', _ad_user('scn-cdany-svc',
                                               "'{0};{1}' -f $u.TrustedToAuthForDelegation, (($u.'msDS-AllowedToDelegateTo' | Sort-Object) -join ',')"),
                              'True;CIFS/kingslanding,CIFS/kingslanding.sevenkingdoms.local'),
    'unconstrained-computer': ('dc02', _ad_computer('castelblack', '$c.TrustedForDelegation'), 'True'),
    'constrained-deleg-kerb': ('dc02', _ad_computer('castelblack', "(@($c.'msDS-AllowedToDelegateTo') | Sort-Object) -join ','"),
                               'HTTP/winterfell,HTTP/winterfell.north.sevenkingdoms.local'),
    'local-admin': ('srv02', "[bool](Get-LocalGroupMember Administrators | Where-Object Name -like '*\\scn-local-admin')", 'True'),
    'webdav': ('srv02', '[bool](Get-Service WebClient -ErrorAction SilentlyContinue)', 'True'),
    'acl-addmember': ('dc01', _acl_user('scn-acl-add-attacker', 'scn-acl-add-group', 'WriteProperty', MEMBER_GUID), 'True'),
    'acl-adminsdholder': ('dc01', _ace('*\\scn-acl-sdh-attacker', '"CN=AdminSDHolder,CN=System,$d"', 'GenericAll'), 'True'),
    'acl-forcechangepassword': ('dc01', _acl_user('scn-acl-fcp-attacker', 'scn-acl-fcp-victim', 'ExtendedRight',
                                                   RESET_PWD_GUID), 'True'),
    'acl-genericall-computer': ('dc01', _ace('*\\scn-acl-gac-attacker', _sam('kingslanding$'), 'GenericAll'), 'True'),
    'acl-genericall-group': ('dc02', _acl_user('scn-acl-gag-attacker', 'scn-acl-gag-group', 'GenericAll'), 'True'),
    'acl-genericall-user': ('dc01', _acl_user('scn-acl-gau-attacker', 'scn-acl-gau-victim', 'GenericAll'), 'True'),
    'acl-genericwrite-user': ('dc01', _acl_user('scn-acl-gwu-attacker', 'scn-acl-gwu-victim', 'GenericWrite'), 'True'),
    'acl-self-membership': ('dc01', _acl_user('scn-acl-sm-attacker', 'scn-acl-sm-group', 'Self', MEMBER_GUID), 'True'),
    'acl-writedacl-ou': ('dc01', _ace('*\\scn-acl-wdo-attacker',
                                     '(Get-ADOrganizationalUnit -LDAPFilter "(ou=scn-acl-wdo)").DistinguishedName',
                                     'WriteDacl'), 'True'),
    'acl-writedacl-user': ('dc01', _acl_user('scn-acl-wdu-attacker', 'scn-acl-wdu-victim', 'WriteDacl'), 'True'),
    'acl-writeowner': ('dc01', _acl_user('scn-acl-wo-attacker', 'scn-acl-wo-group', 'WriteOwner'), 'True'),
    'acl-writeproperty': ('dc01', _acl_user('scn-acl-wp-attacker', 'scn-acl-wp-victim', 'WriteProperty',
                                            inherit='All'), 'True'),
    'anonymous-rpc': ('dc01', _ace('NT AUTHORITY\\ANONYMOUS LOGON', '$d', 'ReadProperty', inherit='All'), 'True'),
    'writespn': ('dc01', _acl_user('scn-wspn-attacker', 'scn-wspn-victim', 'Self', SPN_GUID), 'True'),
    'rbcd': ('dc02', _ace('*\\scn-rbcd-attacker', _sam('castelblack$'), 'GenericWrite'), 'True'),
    'foreign-group-acl': ('dc01', _ace('*\\scn-foreign-group', _sam('kingslanding$'), 'GenericAll'), 'True'),
    'gpo-abuse': ('dc01', GPO_PERMISSION, 'GpoEditDeleteModifySecurity'),
}

SETTING_SCENARIOS = [
    'credssp',
    'defender-off',
    'esc10-case1',
    'esc10-case2',
    'esc11',
    'esc6',
    'esc8',
    'firewall-off',
    'ldap-cbt-off',
    'ldap-signing-off',
    'llmnr',
    'maq',
    'mdns',
    'ntlm-downgrade',
    'printerbug',
    'rc4',
    'sid-history',
    'smb-signing-off',
    'smbv1',
    'webdav',
]


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
    middle = names[len(names) // 2]
    try:
        _reset_base(settings)
        base = {name: _read(ips, name) for name in names}
        assert base[middle] != PROBES[middle][2], f'{middle}: base value {base[middle]!r} already the enabled value'
        start = time.monotonic()
        for name in names:
            assert main(['scenario', 'enable', name]) == 0
        print(f'enable {len(names)} scenarios: {time.monotonic() - start:.0f} s')
        for host in ips.values():
            wait_logon(host, 'Administrator')
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


ACCOUNT_SCENARIOS = [
    'kerberoast',
    'asrep-roast',
    'unconstrained-user',
    'constrained-deleg-any',
    'unconstrained-computer',
    'constrained-deleg-kerb',
    'local-admin',
]


def test_account_scenarios_live():
    run_step(ACCOUNT_SCENARIOS)


ACL_SCENARIOS = [
    'acl-addmember',
    'acl-adminsdholder',
    'acl-forcechangepassword',
    'acl-genericall-computer',
    'acl-genericall-group',
    'acl-genericall-user',
    'acl-genericwrite-user',
    'acl-self-membership',
    'acl-writedacl-ou',
    'acl-writedacl-user',
    'acl-writeowner',
    'acl-writeproperty',
    'anonymous-rpc',
    'writespn',
    'rbcd',
    'foreign-group-acl',
    'gpo-abuse',
]


def test_acl_scenarios_live():
    run_step(ACL_SCENARIOS)
