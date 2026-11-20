$ErrorActionPreference = 'Continue'
if ($env:GOAD_IS_WIN11 -eq 'true') {
    # sysprep /generalize fails on Appx packages installed for a user but not provisioned for all users
    $provisioned = (Get-AppxProvisionedPackage -Online).DisplayName
    Get-AppxPackage -AllUsers | Where-Object { $_.Name -notin $provisioned -and -not $_.IsFramework -and $_.NonRemovable -eq $false } |
        ForEach-Object { Remove-AppxPackage -Package $_.PackageFullName -AllUsers -ErrorAction SilentlyContinue }
}
# C:\Windows\Temp holds Packer's own uploaded scripts; leave it alone. The component store is
# compacted earlier by compact.ps1, followed by a restart, so WinRM is fresh before sysprep.
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue C:\Windows\SoftwareDistribution\Download\*
exit 0
