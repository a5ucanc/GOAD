# Runs from SetupComplete.cmd as SYSTEM on every clone, after sysprep specialize and OOBE.
# Reads guestinfo.goad.* (written by goad into the .vmx), configures the machine, renames it and reboots.
# A startup task sets guestinfo.goad.firstboot=done once the new name is live.
$ErrorActionPreference = 'Stop'
$rpc = 'C:\Program Files\VMware\VMware Tools\rpctool.exe'
function Get-GuestInfo([string]$key) { $v = & $rpc "info-get guestinfo.goad.$key" 2>$null; if ($LASTEXITCODE -ne 0) { return '' } return "$v".Trim() }

try { Unregister-ScheduledTask -TaskName 'goad-sysprep' -Confirm:$false -ErrorAction Stop } catch { }

$ip = Get-GuestInfo 'ip'
if (-not $ip) { Write-Host 'no guestinfo.goad.ip: nothing to do'; exit 0 }
$hostname = Get-GuestInfo 'hostname'
$prefix = [int](Get-GuestInfo 'prefix')
$gateway = Get-GuestInfo 'gateway'
$dns = (Get-GuestInfo 'dns') -split ',' | Where-Object { $_ }
$password = Get-GuestInfo 'password'
$mac = (Get-GuestInfo 'mac').ToUpper().Replace(':', '-')

# lab NIC: found by its static MAC (it may take a moment to appear)
$nic = $null
for ($i = 0; $i -lt 60 -and -not $nic; $i++) {
    $nic = Get-NetAdapter | Where-Object { $_.MacAddress -eq $mac }
    if (-not $nic) { Start-Sleep -Seconds 2 }
}
if (-not $nic) { throw "no network adapter with MAC $mac" }
Set-NetIPInterface -InterfaceIndex $nic.ifIndex -Dhcp Disabled
Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
$params = @{ InterfaceIndex = $nic.ifIndex; IPAddress = $ip; PrefixLength = $prefix }
if ($gateway) { $params.DefaultGateway = $gateway }
New-NetIPAddress @params | Out-Null
Set-DnsClientServerAddress -InterfaceIndex $nic.ifIndex -ServerAddresses $dns
Rename-NetAdapter -Name $nic.Name -NewName 'lab'
Get-NetAdapter | Where-Object { $_.MacAddress -ne $mac } | Select-Object -First 1 | ForEach-Object { Rename-NetAdapter -Name $_.Name -NewName 'nat' }
Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue

# local Administrator: lab password, enabled (disabled by default on client Windows)
net user Administrator $password | Out-Null
net user Administrator /active:yes | Out-Null

# WinRM: Packer's Basic/unencrypted settings off; Ansible uses NTLM with message encryption (psrp)
winrm set winrm/config/service/auth '@{Basic="false"}' | Out-Null
winrm set winrm/config/service '@{AllowUnencrypted="false"}' | Out-Null

# the done marker is set after the rename reboot, by a one-shot startup task
$done = "if (`$env:COMPUTERNAME -eq '$hostname'.ToUpper()) { & '$rpc' 'info-set guestinfo.goad.firstboot done'; Unregister-ScheduledTask -TaskName goad-firstboot-done -Confirm:`$false }"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$done`""
Register-ScheduledTask -TaskName goad-firstboot-done -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -User SYSTEM -RunLevel Highest -Force | Out-Null

if ($env:COMPUTERNAME -ne $hostname.ToUpper()) { Rename-Computer -NewName $hostname -Force }
shutdown.exe /r /t 10 /c "goad first boot"
