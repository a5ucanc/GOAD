# Mount the Exchange ISO (once) and return the root of its drive, such as E:\
param([string]$Path)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$image = Get-DiskImage -ImagePath $Path
if (-not $image.Attached) {
    $image = Mount-DiskImage -ImagePath $Path -PassThru
    $Ansible.Changed = $true
}
$letter = ($image | Get-Volume).DriveLetter
if (-not $letter) { throw "no drive letter for the mounted image $Path" }
$Ansible.Result = "${letter}:\"
