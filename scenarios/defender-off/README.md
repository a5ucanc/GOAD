# defender-off

Defender real-time protection off on a member server. Sets `defender.realtime` to `off` on a host providing `member_server`.

Attack:

Drop and run tooling (mimikatz, Rubeus) on the host without AV detection.

How to verify:

    Get-MpComputerStatus | Select RealTimeProtectionEnabled   # False when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
