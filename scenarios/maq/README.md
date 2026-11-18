# maq

Machine account quota 10: any domain user can create computer accounts. Sets `dc.maq` to `10` on a domain controller (default: the root DC).

Attack:

Create a computer account, then use it for RBCD or noPAC:

    addcomputer.py -computer-name 'scnpc$' -computer-pass 'Aa1234567890!' <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip>

The `rbcd` scenario depends on this one (on the DC of the target's domain). Disable restores quota 0 and deletes every computer account created through the quota (`mS-DS-CreatorSID` set).

How to verify:

    Get-ADObject (Get-ADDomain).DistinguishedName -Properties ms-DS-MachineAccountQuota   # 10 when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
