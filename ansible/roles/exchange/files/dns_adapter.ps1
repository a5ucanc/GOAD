# Exchange transport resolves names through the lab adapter only (the NAT adapter's DNS knows no lab
# domain), and external names through the lab's DNS forwarder, as main's ludus_exchange did.
param([string]$Name, [string]$LabAddress, [string]$Forwarder)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
Add-PSSnapin -Name Microsoft.Exchange.Management.PowerShell.SnapIn
$ip = Get-NetIPAddress -IPAddress $LabAddress
$guid = [guid](Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex).InterfaceGuid
$transport = Get-TransportService -Identity $Name
$servers = @($transport.ExternalDNSServers | ForEach-Object { [string]$_ })
if (-not ($transport.InternalDNSAdapterEnabled -and $transport.InternalDNSAdapterGuid -eq $guid -and
          -not $transport.ExternalDNSAdapterEnabled -and $servers.Count -eq 1 -and $servers[0] -eq $Forwarder)) {
    Set-TransportService -Identity $Name -InternalDNSAdapterEnabled $true -InternalDNSAdapterGuid $guid `
        -ExternalDNSAdapterEnabled $false -ExternalDNSServers $Forwarder
    Restart-Service -Name MSExchangeTransport
    $Ansible.Changed = $true
}
