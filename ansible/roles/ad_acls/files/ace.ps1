# Add explicit Allow ACEs for one lab.yml acls entry, idempotently. Ported from main's
# ansible/roles/scenario_acl/files/scenario_ace.ps1 (add mode only): the target DN is resolved
# here from the object kind and name instead of being passed in.
param(
    [string]$Principal,
    [string]$Kind,
    [string]$Name,
    [string]$Right,
    [string]$Inherit
)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
Import-Module ActiveDirectory

$root = Get-ADRootDSE
$domainDn = $root.defaultNamingContext
switch ($Kind) {
    { $_ -in 'user', 'group', 'computer' } {
        $o = Get-ADObject -LDAPFilter "(sAMAccountName=$Name)"
        if (-not $o) { throw "$Kind $Name not found" }
        $targetDn = $o.DistinguishedName
    }
    'ou' { $targetDn = "OU=$Name,$domainDn" }
    'domain' { $targetDn = $domainDn }
    'adminsdholder' { $targetDn = "CN=AdminSDHolder,CN=System,$domainDn" }
    'template' { $targetDn = "CN=$Name,CN=Certificate Templates,CN=Public Key Services,CN=Services,$($root.configurationNamingContext)" }
    default { throw "unsupported object kind $Kind" }
}
$null = Get-ADObject -Identity $targetDn

# A <NETBIOS>\<name> or well-known name resolves through LSA (across trusts); a bare name is an
# account of this domain, looked up by sAMAccountName. Everyone has no AD object, so LSA again.
$sid = $null
if ($Principal -notmatch '\\') {
    $obj = Get-ADObject -LDAPFilter "(sAMAccountName=$Principal)" -Properties objectSid
    if ($obj) { $sid = $obj.objectSid }
}
if (-not $sid) {
    try {
        $sid = (New-Object Security.Principal.NTAccount $Principal).Translate([Security.Principal.SecurityIdentifier])
    } catch { throw "principal $Principal not found" }
}

# Each right maps to one or more (ActiveDirectoryRights, object type GUID) pairs.
$empty = '00000000-0000-0000-0000-000000000000'
$map = @{
    'AddMember'           = @(, @('WriteProperty', 'bf9679c0-0de6-11d0-a285-00aa003049e2'))
    'SelfMembership'      = @(, @('Self', 'bf9679c0-0de6-11d0-a285-00aa003049e2'))
    'WriteSPN'            = @(, @('Self', 'f3a64788-5306-11d1-a9c5-0000f80367c1'))
    'ForceChangePassword' = @(, @('ExtendedRight', '00299570-246d-11d0-a768-00aa006e0529'))
    'ReadAll'             = @(@('ReadProperty', $empty), @('GenericExecute', $empty))
    # Certificate-Enrollment, for the adcs role's template enroll grants (not a lab.yml acls right).
    'Enroll'              = @(, @('ExtendedRight', '0e10c968-78fb-11d2-90d4-00c04f79dc55'))
}
# Assigned in the branches: an if expression would unroll a one-pair list into its two strings.
if ($map.ContainsKey($Right)) { $pairs = $map[$Right] } else { $pairs = @(, @($Right, $empty)) }
$inheritance = [DirectoryServices.ActiveDirectorySecurityInheritance]$(if ($Inherit -eq 'all') { 'All' } else { 'None' })

$path = "AD:$targetDn"
$acl = Get-Acl -Path $path
$added = $false
foreach ($pair in $pairs) {
    $rights = [DirectoryServices.ActiveDirectoryRights]$pair[0]
    $guid = [guid]$pair[1]
    # Windows merges ACEs that differ only by rights, so compare rights as bit sets.
    $same = @($acl.GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier]) | Where-Object {
        $_.IdentityReference -eq $sid -and $_.AccessControlType -eq 'Allow' -and
        $_.ObjectType -eq $guid -and $_.InheritanceType -eq $inheritance -and
        ($_.ActiveDirectoryRights -band $rights) -eq $rights
    })
    if (-not $same) {
        $acl.AddAccessRule((New-Object DirectoryServices.ActiveDirectoryAccessRule $sid, $rights, 'Allow', $guid, $inheritance))
        $added = $true
    }
}
if ($added) {
    Set-Acl -Path $path -AclObject $acl
    $Ansible.Changed = $true
}
