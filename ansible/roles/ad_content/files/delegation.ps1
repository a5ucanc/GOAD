# Ported from main's constrained-deleg-any, constrained-deleg-kerb, unconstrained-user and
# unconstrained-computer scenarios (add mode). Unconstrained sets TRUSTED_FOR_DELEGATION; constrained
# adds msDS-AllowedToDelegateTo values, and protocol_transition sets TRUSTED_TO_AUTH_FOR_DELEGATION.
param([string]$Kind, [string]$Name, [bool]$Unconstrained, [string[]]$Constrained, [bool]$ProtocolTransition)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$props = 'msDS-AllowedToDelegateTo', 'userAccountControl'
if ($Kind -eq 'computer') {
    $o = Get-ADComputer -Identity "$Name$" -Properties $props
} else {
    $o = Get-ADUser -Identity $Name -Properties $props
}
if ($Unconstrained -and -not ($o.userAccountControl -band 0x80000)) {
    Set-ADAccountControl -Identity $o -TrustedForDelegation $true
    $Ansible.Changed = $true
}
if ($ProtocolTransition -and -not ($o.userAccountControl -band 0x1000000)) {
    Set-ADAccountControl -Identity $o -TrustedToAuthForDelegation $true
    $Ansible.Changed = $true
}
foreach ($t in $Constrained) {
    if (@($o.'msDS-AllowedToDelegateTo') -notcontains $t) {
        Set-ADObject -Identity $o.DistinguishedName -Add @{'msDS-AllowedToDelegateTo' = $t}
        $Ansible.Changed = $true
    }
}
