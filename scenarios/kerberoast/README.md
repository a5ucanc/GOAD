# kerberoast

Creates `svc_kerb` (password `Aa1234567890!`) with SPN `MSSQLSvc/svc-kerb.<domain>:1433`, in `CN=Users`.

Attack:

    impacket-GetUserSPNs <domain>/administrator:'Aa1234567890!' -dc-ip <dc ip> -request

The scenario does not touch encryption types. With `kerberos.rc4` disabled the ticket is AES (`$krb5tgs$18$`, hashcat mode 19700). RC4 roasting needs the `kerberos.rc4` setting scenario.

Disable removes the account.
