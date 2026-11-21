"""Catalogue of lab.yml security settings: key -> (scope, accepted values)."""
from typing import Any, Dict, Tuple

_EN = ('disabled', 'enabled')
_ONOFF = ('on', 'off')
_DIGITS6 = tuple(str(n) for n in range(6))

SETTINGS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    'host.tier': ('all', ('0', '1', '2')),
    'net.llmnr': ('all', _EN),
    'net.nbtns': ('all', _EN),
    'net.mdns': ('all', _EN),
    'smb.v1': ('all', _EN),
    'kerberos.rc4': ('all', _EN),
    'net.webclient': ('all', ('absent', 'present')),
    'smb.signing': ('all', ('required', 'optional')),
    'ntlm.lmcompat': ('all', _DIGITS6),
    'defender.realtime': ('all', _ONOFF),
    'firewall.state': ('all', _ONOFF),
    'lsa.ppl': ('all', _ONOFF),
    'defender.asr_lsass': ('all', ('block', 'off')),
    'winrm.credssp': ('all', ('disabled', 'server', 'client')),
    'ldap.signing': ('dc', ('required', 'none')),
    'ldap.channel_binding': ('dc', ('always', 'never')),
    'dc.maq': ('dc', tuple(str(n) for n in range(11))),
    'dc.spooler': ('dc', _EN),
    'trust.sid_history': ('dc', _EN),
    'dc.strong_cert_binding': ('dc', ('0', '1', '2')),
    'dc.cert_mapping': ('dc', ('absent', '0x4')),
    'adcs.web_enrollment': ('ca', _ONOFF),
    'adcs.editf_san': ('ca', _ONOFF),
    'adcs.enforce_encrypt': ('ca', _ONOFF),
}

SETTING_LAYERS = ('all', 'dc', 'server', 'workstation')
GROUP_SCOPES = ('global', 'universal', 'domainlocal')


def normalize_value(value: Any) -> str:
    """YAML value to the string form used in the catalogue (bool before int: bool is an int)."""
    if isinstance(value, bool):
        return 'on' if value else 'off'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    raise TypeError(f'unsupported setting value {value!r}')
