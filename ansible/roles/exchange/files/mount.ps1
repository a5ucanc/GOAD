# Mount the Exchange ISO (once) and return the root of its drive, such as E:\
param([string]$Path)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$image = Get-DiskImage -ImagePath $Path
if (-not $image.Attached) {
    $image = Mount-DiskImage -ImagePath $Path -PassThru
    $Ansible.Changed = $true
}
# The volume can lack its drive letter for a moment after the mount: poll for up to 30 s
$letter = $null
foreach ($try in 1..30) {
    $letter = (Get-DiskImage -ImagePath $Path | Get-Volume).DriveLetter
    if ($letter) { break }
    Start-Sleep -Seconds 1
}
if (-not $letter) { throw "no drive letter for the mounted image $Path after 30 s" }
$Ansible.Result = "${letter}:\"
