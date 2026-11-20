# Every .cer/.crt at the root of an attached disc (goad's ca_certs_dir) goes into the machine root store.
$ErrorActionPreference = 'Stop'
# the disc may hold the files at its root or inside the copied folder: search two levels
$certs = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -ne 'C:\' } |
    ForEach-Object { Get-ChildItem -Path $_.Root -File -Recurse -Depth 1 -ErrorAction SilentlyContinue } |
    Where-Object { $_.Extension -in '.cer', '.crt' }
foreach ($cert in $certs) {
    Write-Host "importing $($cert.FullName)"
    Import-Certificate -FilePath $cert.FullName -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
}
Write-Host "$(@($certs).Count) certificate(s) imported"
if ($env:GOAD_CA_EXPECTED -eq '1' -and @($certs).Count -eq 0) { throw 'ca_certs_dir is set but no certificate was found' }
