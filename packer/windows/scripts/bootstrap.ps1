# First logon of the install: open WinRM for Packer only. firstboot.ps1 locks it down again on every clone.
$ErrorActionPreference = 'Stop'
Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private
Enable-PSRemoting -Force -SkipNetworkProfileCheck
winrm set winrm/config/service/auth '@{Basic="true"}'
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="2048"}'
Set-Item -Path WSMan:\localhost\Service\Auth\CredSSP -Value $false
New-ItemProperty -Path HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System -Name LocalAccountTokenFilterPolicy -Value 1 -PropertyType DWord -Force | Out-Null
netsh advfirewall firewall add rule name="WinRM-HTTP" dir=in localport=5985 protocol=TCP action=allow profile=any
Set-Service -Name WinRM -StartupType Automatic
Restart-Service WinRM
