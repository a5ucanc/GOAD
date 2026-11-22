# Server templates carry the AD DS and DNS roles installed but not configured; provisioning only configures them.
# The AD CS role is left out: dcpromo refuses to run while it is installed, so provisioning adds it to CA hosts
# (role ca_feature). Its management tools (RSAT-ADCS) stay.
$ErrorActionPreference = 'Stop'
if ($env:GOAD_IS_SERVER -ne 'true') { Write-Host 'not a server: no features'; exit 0 }
Install-WindowsFeature -Name AD-Domain-Services, DNS, RSAT-AD-Tools, RSAT-DNS-Server, RSAT-ADCS -IncludeManagementTools | Format-Table -AutoSize
