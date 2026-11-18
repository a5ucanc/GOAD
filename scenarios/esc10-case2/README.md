# esc10-case2

Schannel maps certificates by UPN (CertificateMappingMethods 0x4, ESC10 case 2). Sets `dc.cert_mapping` to `0x4` on a domain controller (default: the root DC).

Attack:

Same UPN swap as ESC10 case 1, targeting a computer or user without a UPN, then authenticate over Schannel (LDAPS):

    certipy auth -pfx <dc>.pfx -dc-ip <dc ip> -ldap-shell

How to verify:

    reg query HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\Schannel /v CertificateMappingMethods   # 0x4 when enabled, value absent when disabled

Disable restores the value declared for the host in the lab's `base_settings`.
