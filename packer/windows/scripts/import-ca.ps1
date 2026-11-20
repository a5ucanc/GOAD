# Every .cer/.crt on goad's disc (label "goad": autounattend, bootstrap and the files of ca_certs_dir)
# goes into the machine root store. Other discs (the Windows ISO ships .cer files too) are ignored.
$ErrorActionPreference = 'Stop'
$disc = Get-Volume | Where-Object { $_.DriveType -eq 'CD-ROM' -and $_.FileSystemLabel -eq 'goad' } | Select-Object -First 1
if (-not $disc) { throw 'goad disc (label goad) not found' }
# the files may sit at the disc root or inside the copied folder
$certs = @(Get-ChildItem -Path "$($disc.DriveLetter):\" -File -Recurse -Depth 1 -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.cer', '.crt' })
foreach ($cert in $certs) {
    Write-Host "importing $($cert.FullName)"
    Import-Certificate -FilePath $cert.FullName -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
}
Write-Host "$($certs.Count) certificate(s) imported"
if ($env:GOAD_CA_EXPECTED -eq '1' -and $certs.Count -eq 0) { throw 'ca_certs_dir is set but no certificate was found' }
