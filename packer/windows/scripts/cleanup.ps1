$ErrorActionPreference = 'Continue'
if ($env:GOAD_IS_WIN11 -eq 'true') {
    # sysprep /generalize fails on Appx packages installed for a user but not provisioned for all users
    $provisioned = (Get-AppxProvisionedPackage -Online).DisplayName
    Get-AppxPackage -AllUsers | Where-Object { $_.Name -notin $provisioned -and -not $_.IsFramework -and $_.NonRemovable -eq $false } |
        ForEach-Object { Remove-AppxPackage -Package $_.PackageFullName -AllUsers -ErrorAction SilentlyContinue }
}
Dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase /Quiet
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $env:TEMP\*, C:\Windows\Temp\*, C:\Windows\SoftwareDistribution\Download\*
exit 0
