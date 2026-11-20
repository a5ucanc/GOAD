# Packer's shutdown_command. Running sysprep directly under WinRM drops the guest network before
# WinRM answers, so the command fails. Instead, start sysprep from a SYSTEM scheduled task a few
# seconds later, outside the WinRM shell, and return at once. Packer then waits for the power-off.
# firstboot.ps1 removes the task on every clone.
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\Sysprep\sysprep.exe" `
    -Argument '/generalize /oobe /shutdown /quiet /unattend:C:\goad\unattend.xml'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(20)
Register-ScheduledTask -TaskName 'goad-sysprep' -Action $action -Trigger $trigger -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
Write-Host 'sysprep scheduled'
