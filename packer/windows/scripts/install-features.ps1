# Server templates carry the AD roles installed but not configured; provisioning only configures them.
$ErrorActionPreference = 'Stop'
if ($env:GOAD_IS_SERVER -ne 'true') { Write-Host 'not a server: no features'; exit 0 }
Install-WindowsFeature -Name AD-Domain-Services, DNS, ADCS-Cert-Authority, RSAT-AD-Tools, RSAT-DNS-Server, RSAT-ADCS -IncludeManagementTools | Format-Table -AutoSize
