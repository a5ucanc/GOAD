# Set-DcGpoValue writes one registry value into the Default Domain Controllers Policy, which would
# otherwise re-apply its own value. Prepended to a setting's script with lookup('file'); returns
# $true when it changed the policy. Call it on domain controllers only.
function Set-DcGpoValue {
param(
    [Parameter(Mandatory)][string]$RegKey,
    [Parameter(Mandatory)][string]$Value
)

Import-Module ActiveDirectory
$domain = Get-ADDomain
$guid = '{6AC1786C-016F-11D2-945F-00C04fB984F9}'
# Local SYSVOL path: a UNC path would be a second hop from the PSRP session.
$sysvol = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Netlogon\Parameters').SysVol
$gpoDir = "$sysvol\$($domain.DNSRoot)\Policies\$guid"
$inf = "$gpoDir\MACHINE\Microsoft\Windows NT\SecEdit\GptTmpl.inf"
$ini = "$gpoDir\GPT.ini"

$lines = @(Get-Content -Path $inf)
$wanted = "$RegKey=4,$Value"
$pattern = '^\s*' + [regex]::Escape($RegKey) + '\s*='
$out = New-Object System.Collections.Generic.List[string]
$inSection = $false
$sectionSeen = $false
$done = $false
$changed = $false
foreach ($l in $lines) {
    if ($l -match '^\s*\[(.+)\]\s*$') {
        if ($inSection -and -not $done) { $out.Add($wanted); $done = $true; $changed = $true }
        $inSection = ($Matches[1] -eq 'Registry Values')
        if ($inSection) { $sectionSeen = $true }
        $out.Add($l); continue
    }
    if ($inSection -and $l -match $pattern) {
        if ($l.Trim() -ne $wanted) { $changed = $true }
        if (-not $done) { $out.Add($wanted); $done = $true } else { $changed = $true }
        continue
    }
    $out.Add($l)
}
if (-not $done) {
    if (-not $sectionSeen) { $out.Add('[Registry Values]') }
    $out.Add($wanted); $changed = $true
}
if (-not $changed) { return $false }

Set-Content -Path $inf -Value $out -Encoding Unicode
# Bump GPO version so the change replicates
$iniText = Get-Content -Path $ini -Raw
if ($iniText -match 'Version\s*=\s*(\d+)') {
    $new = [int]$Matches[1] + 1
    $iniText = $iniText -replace 'Version\s*=\s*\d+', "Version=$new"
    Set-Content -Path $ini -Value $iniText -Encoding Ascii -NoNewline
}
$dn = "CN=$guid,CN=Policies,CN=System,$($domain.DistinguishedName)"
$obj = Get-ADObject -Identity $dn -Properties versionNumber
Set-ADObject -Identity $dn -Replace @{ versionNumber = ([int]$obj.versionNumber + 1) }
gpupdate /force | Out-Null
return $true
}
