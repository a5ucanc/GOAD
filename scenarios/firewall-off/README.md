# firewall-off

Windows firewall off on a member server. Sets `firewall.state` to `off` on a host providing `member_server`.

Attack:

Every listening service of the host is reachable from the network:

    nmap -p- <host ip>

How to verify:

    Get-NetFirewallProfile | Select Name,Enabled   # False when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
