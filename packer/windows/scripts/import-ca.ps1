# Every .cer/.crt at the root of an attached disc (goad's ca_certs_dir) goes into the machine root store.
$ErrorActionPreference = 'Stop'
$certs = Get-PSDrive -PSProvider FileSystem | ForEach-Object { Get-ChildItem -Path $_.Root -File -ErrorAction SilentlyContinue } |
    Where-Object { $_.Extension -in '.cer', '.crt' }
foreach ($cert in $certs) {
    Write-Host "importing $($cert.FullName)"
    Import-Certificate -FilePath $cert.FullName -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
}
Write-Host "$(@($certs).Count) certificate(s) imported"
