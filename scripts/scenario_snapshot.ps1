# Stable text snapshot of everything a scenario can change on this host.
# Used by tests/live/run_scenario_cycle.sh to prove that disable leaves no residue.
$ErrorActionPreference = 'Continue'
$out = New-Object System.Collections.Generic.List[string]
function add($k, $v) { $out.Add("$k = $(@($v) -join ' ; ')") }
function reg($path, $name) {
    $v = (Get-ItemProperty -Path $path -Name $name -ErrorAction SilentlyContinue).$name
    add "reg $path\$name" $(if ($null -eq $v) { '<absent>' } else { $v })
}

# settings behind base_setting keys
reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient' EnableMulticast
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\Dnscache\Parameters' EnableMDNS
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' RequireSecuritySignature
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters' EnableSecuritySignature
reg 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' LmCompatibilityLevel
reg 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' RunAsPPL
reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Kerberos\Parameters' SupportedEncryptionTypes
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\NTDS\Parameters' LDAPServerIntegrity
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\NTDS\Parameters' LdapEnforceChannelBindings
reg 'HKLM:\SYSTEM\CurrentControlSet\Services\Kdc' StrongCertificateBindingEnforcement
reg 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\Schannel' CertificateMappingMethods
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Services\NetBT\Parameters\Interfaces' -ErrorAction SilentlyContinue | ForEach-Object {
    add "netbt $($_.PSChildName)" (Get-ItemProperty $_.PSPath -Name NetbiosOptions -ErrorAction SilentlyContinue).NetbiosOptions }
add 'defender realtime off' (Get-MpPreference).DisableRealtimeMonitoring
Get-NetFirewallProfile | ForEach-Object { add "firewall $($_.Name)" $_.Enabled }
add 'smb1' (Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol).State
$wd = Get-WindowsFeature WebDAV-Redirector -ErrorAction SilentlyContinue
if ($wd) { add 'webdav' $wd.InstallState }
add 'credssp server' (Get-Item WSMan:\localhost\Service\Auth\CredSSP).Value
add 'credssp client' (Get-Item WSMan:\localhost\Client\Auth\CredSSP).Value
$sp = Get-Service Spooler -ErrorAction SilentlyContinue
if ($sp) { add 'spooler' "$($sp.StartType)/$($sp.Status)" }
add 'local administrators' ((Get-LocalGroupMember -Group Administrators -ErrorAction SilentlyContinue | ForEach-Object { $_.SID.Value } | Sort-Object))
secedit /export /cfg "$env:TEMP\scn_rights.inf" /areas USER_RIGHTS | Out-Null
Get-Content "$env:TEMP\scn_rights.inf" | Where-Object { $_ -match '^SeDeny' } | Sort-Object | ForEach-Object { $out.Add("right $_") }

$isDc = (Get-CimInstance Win32_ComputerSystem).DomainRole -ge 4
if ($isDc) {
    Import-Module ActiveDirectory
    $root = Get-ADRootDSE
    $d = $root.defaultNamingContext
    $c = $root.configurationNamingContext
    Get-ADObject -LDAPFilter '(|(name=scn-*)(sAMAccountName=scn-*)(displayName=scn-*))' -SearchBase $d | ForEach-Object { $out.Add("scn object $($_.DistinguishedName)") }
    Get-ADObject -LDAPFilter '(|(name=scn-*)(displayName=IssuancePolicyESC13)(displayName=ESC*))' -SearchBase $c | ForEach-Object { $out.Add("config object $($_.DistinguishedName)") }
    Get-ADUser -Filter * -Properties servicePrincipalName, userAccountControl, msDS-AllowedToDelegateTo | Sort-Object SamAccountName | ForEach-Object {
        add "user $($_.SamAccountName)" "uac=$($_.userAccountControl) spn=$(@($_.servicePrincipalName) -join ',') a2d=$(@($_.'msDS-AllowedToDelegateTo') -join ',')" }
    add 'groups' ((Get-ADGroup -Filter * | ForEach-Object SamAccountName | Sort-Object))
    add 'ous' ((Get-ADOrganizationalUnit -Filter * | ForEach-Object DistinguishedName | Sort-Object))
    function sddl($dn) { try { (Get-Acl "AD:$dn").Sddl } catch { '<missing>' } }
    add 'sddl domain root' (sddl $d)
    add 'sddl AdminSDHolder' (sddl "CN=AdminSDHolder,CN=System,$d")
    add 'sddl Domain Admins' (sddl (Get-ADGroup 'Domain Admins').DistinguishedName)
    add 'sddl WebServer template' (sddl "CN=WebServer,CN=Certificate Templates,CN=Public Key Services,CN=Services,$c")
    Get-ADComputer -Filter * -Properties userAccountControl, msDS-AllowedToDelegateTo, msDS-AllowedToActOnBehalfOfOtherIdentity, msDS-KeyCredentialLink, mS-DS-CreatorSID | Sort-Object Name | ForEach-Object {
        add "computer $($_.Name)" "uac=$($_.userAccountControl) a2d=$(@($_.'msDS-AllowedToDelegateTo') -join ',') rbcd=$([bool]$_.'msDS-AllowedToActOnBehalfOfOtherIdentity') kcl=$(@($_.'msDS-KeyCredentialLink').Count) creator=$($_.'mS-DS-CreatorSID')"
        add "sddl computer $($_.Name)" (sddl $_.DistinguishedName)
    }
    add 'fsp' ((Get-ADObject -SearchBase "CN=ForeignSecurityPrincipals,$d" -Filter * | ForEach-Object Name | Sort-Object))
    add 'gpos' ((Get-GPO -All | ForEach-Object DisplayName | Sort-Object))
    add 'gplink' (Get-ADObject $d -Properties gPLink).gPLink
    add 'maq' (Get-ADObject $d -Properties ms-DS-MachineAccountQuota).'ms-DS-MachineAccountQuota'
    add 'administrators' ((Get-ADGroupMember Administrators | ForEach-Object SamAccountName | Sort-Object))
    add 'published templates' ((Get-ADObject -SearchBase "CN=Enrollment Services,CN=Public Key Services,CN=Services,$c" -Filter * -Properties certificateTemplates).certificateTemplates | Sort-Object)
    Get-ADObject -SearchBase "CN=System,$d" -SearchScope OneLevel -LDAPFilter '(objectClass=trustedDomain)' -Properties trustAttributes | ForEach-Object { add "trust $($_.Name)" $_.trustAttributes }
}

if (Get-Service certsvc -ErrorAction SilentlyContinue) {
    add 'ca editflags' ((certutil -getreg policy\EditFlags | Select-String 'EditFlags REG_DWORD') -join '')
    add 'ca interfaceflags' ((certutil -getreg CA\InterfaceFlags | Select-String 'InterfaceFlags REG_DWORD') -join '')
    add 'ca security' ((certutil -getreg CA\Security | Select-String 'Allow') | ForEach-Object { $_.Line.Trim() } | Sort-Object)
    add 'ca web enrollment' (Get-WindowsFeature ADCS-Web-Enrollment).InstallState
}

$sql = Get-Service 'MSSQL$SQLEXPRESS', 'MSSQLSERVER' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sql) {
    $q = "SET NOCOUNT ON; SELECT 'login ' + name FROM sys.server_principals WHERE name LIKE '%scn-%'; SELECT 'server ' + name FROM sys.servers; SELECT 'msdb user ' + name FROM msdb.sys.database_principals WHERE name LIKE '%scn-%'; SELECT 'config ' + name + '=' + CAST(value_in_use AS varchar(10)) FROM sys.configurations WHERE name IN ('xp_cmdshell','show advanced options')"
    SqlCmd -S 127.0.0.1,1433 -E -h -1 -W -Q $q | Where-Object { $_ } | ForEach-Object { $out.Add("sql $_") }
}

if (Get-Service W3SVC -ErrorAction SilentlyContinue) {
    add 'wwwroot' ((Get-ChildItem C:\inetpub\wwwroot -Force | ForEach-Object Name | Sort-Object))
}

$out | Sort-Object
