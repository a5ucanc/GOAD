# Is Exchange Server installed on this host? Yes when the Exchange snap-in is registered, no setup
# watermark is left behind (an interrupted setup leaves one) and Get-ExchangeServer lists the host.
param([string]$Name)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$installed = $false
if (Get-PSSnapin -Registered -Name Microsoft.Exchange.Management.PowerShell.SnapIn -ErrorAction SilentlyContinue) {
    $watermark = Get-ChildItem -Path HKLM:\SOFTWARE\Microsoft\ExchangeServer\v15 -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.GetValueNames() -contains 'Watermark' }
    if (-not $watermark) {
        Add-PSSnapin -Name Microsoft.Exchange.Management.PowerShell.SnapIn
        $installed = [bool](Get-ExchangeServer -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $Name })
    }
}
$Ansible.Result = @{ installed = $installed }
