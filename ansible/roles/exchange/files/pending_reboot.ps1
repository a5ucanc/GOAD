# Does Windows wait for a reboot? Exchange setup refuses to run until it happened.
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$pending = (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending') -or
           (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or
           [bool](Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' `
                      -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
$Ansible.Result = @{ pending = $pending }
