# smbv1

SMBv1 enabled on a member server. Sets `smb.v1` to `enabled` on a host providing `member_server`.

Attack:

SMBv1 exploits and downgrade (EternalBlue on an unpatched host, NTLMv1 over SMB1):

    nmap -p445 --script smb-protocols <host ip>

How to verify:

    Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol   # Enabled when enabled (a reboot may follow install and uninstall)

Disable restores the value declared for the host in the lab's `base_settings`.
