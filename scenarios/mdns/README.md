# mdns

mDNS enabled on a member server. Sets `net.mdns` to `enabled` on a host providing `member_server`.

Attack:

Poison mDNS name resolution:

    responder -I <iface>

How to verify:

    reg query HKLM\SYSTEM\CurrentControlSet\Services\Dnscache\Parameters /v EnableMDNS   # 0x1 when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
