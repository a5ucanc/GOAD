# credssp

WinRM CredSSP server role enabled on a member server. Sets `winrm.credssp` to `server` on a host providing `member_server`.

Attack:

A client that connects with CredSSP sends reusable credentials to the host; dump them from LSASS after compromising the host:

    Enter-PSSession <host> -Authentication CredSSP -Credential <user>

How to verify:

    Get-WSManCredSSP   # 'This computer is configured to receive credentials' when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
