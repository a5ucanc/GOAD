# Add or remove one explicit Allow ACE on an AD object, idempotently.
# Target DN may use %DOMAIN% (domain naming context) and %CONFIG% (configuration naming context).
param(
    [string]$Principal,
    [string]$TargetDn,
    [string]$Right,
    [string]$Inheritance,
    [string]$Mode
)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
Import-Module ActiveDirectory

$root = Get-ADRootDSE
$TargetDn = $TargetDn.Replace('%DOMAIN%', $root.defaultNamingContext).Replace('%CONFIG%', $root.configurationNamingContext)

$sid = $null
try {
    if ($Principal -match '\\') {
        $sid = (New-Object Security.Principal.NTAccount $Principal).Translate([Security.Principal.SecurityIdentifier])
    } else {
        $obj = Get-ADObject -LDAPFilter "(sAMAccountName=$Principal)" -Properties objectSid
        if ($obj) { $sid = $obj.objectSid }
    }
} catch { $sid = $null }
if (-not $sid) {
    if ($Mode -eq 'remove') { return }
    throw "principal $Principal not found"
}

try { $null = Get-ADObject -Identity $TargetDn } catch {
    if ($Mode -eq 'remove') { return }
    throw "target $TargetDn not found"
}

$extended = @{
    'Ext-User-Force-Change-Password' = @('ExtendedRight', '00299570-246d-11d0-a768-00aa006e0529')
    'Ext-Write-Self-Membership'      = @('WriteProperty', 'bf9679c0-0de6-11d0-a285-00aa003049e2')
    'Ext-Self-Self-Membership'       = @('Self', 'bf9679c0-0de6-11d0-a285-00aa003049e2')
    'Ext-Validated-SPN'              = @('Self', 'f3a64788-5306-11d1-a9c5-0000f80367c1')
    'Ext-Enroll'                     = @('ExtendedRight', '0e10c968-78fb-11d2-90d4-00c04f79dc55')
}
if ($extended.ContainsKey($Right)) {
    $rights = [DirectoryServices.ActiveDirectoryRights]$extended[$Right][0]
    $guid = [guid]$extended[$Right][1]
} else {
    $rights = [DirectoryServices.ActiveDirectoryRights]$Right
    $guid = [guid]::Empty
}
$inherit = [DirectoryServices.ActiveDirectorySecurityInheritance]$Inheritance

$path = "AD:$TargetDn"
$acl = Get-Acl -Path $path
# Windows merges ACEs that differ only by rights, so compare rights as bit sets.
$same = @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]) | Where-Object {
    $_.IdentityReference -eq $sid -and $_.AccessControlType -eq 'Allow' -and
    $_.ObjectType -eq $guid -and $_.InheritanceType -eq $inherit
})
$ace = New-Object DirectoryServices.ActiveDirectoryAccessRule $sid, $rights, 'Allow', $guid, $inherit

if ($Mode -eq 'add') {
    if (-not ($same | Where-Object { ($_.ActiveDirectoryRights -band $rights) -eq $rights })) {
        $acl.AddAccessRule($ace)
        Set-Acl -Path $path -AclObject $acl
        $Ansible.Changed = $true
    }
} else {
    # strips only this scenario's rights bits from the matching explicit ACEs
    if ($same | Where-Object { ($_.ActiveDirectoryRights -band $rights) -ne 0 }) {
        $null = $acl.RemoveAccessRule($ace)
        Set-Acl -Path $path -AclObject $acl
        $Ansible.Changed = $true
    }
}
