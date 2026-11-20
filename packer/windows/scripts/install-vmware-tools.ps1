$ErrorActionPreference = 'Stop'
$setup = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Join-Path $_.Root 'setup64.exe' } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $setup) { throw 'VMware Tools setup64.exe not found on any drive' }
Write-Host "installing VMware Tools from $setup"
$p = Start-Process -FilePath $setup -ArgumentList '/S /v "/qn REBOOT=R ADDLOCAL=ALL"' -Wait -PassThru
# 3010: success, reboot required
if ($p.ExitCode -notin 0, 3010) { throw "VMware Tools setup failed: $($p.ExitCode)" }
