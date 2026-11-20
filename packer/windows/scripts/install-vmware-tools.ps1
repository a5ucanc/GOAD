$ErrorActionPreference = 'Stop'
# The VMware Tools disc is labelled "VMware Tools"; newer ISOs ship setup.exe only (older ones setup64.exe).
# The Windows install disc also has a setup.exe, so the label decides.
$volume = Get-Volume | Where-Object { $_.DriveType -eq 'CD-ROM' -and $_.FileSystemLabel -like 'VMware Tools*' } | Select-Object -First 1
if (-not $volume) { throw 'VMware Tools disc not found' }
$setup = 'setup64.exe', 'setup.exe' | ForEach-Object { "$($volume.DriveLetter):\$_" } | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $setup) { throw "no setup64.exe or setup.exe on $($volume.DriveLetter):" }
Write-Host "installing VMware Tools from $setup"
$p = Start-Process -FilePath $setup -ArgumentList '/S /v "/qn REBOOT=R ADDLOCAL=ALL"' -Wait -PassThru
# 3010: success, reboot required
if ($p.ExitCode -notin 0, 3010) { throw "VMware Tools setup failed: $($p.ExitCode)" }
