$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path C:\goad, C:\Windows\Setup\Scripts | Out-Null
# no hibernation file, no sleep, no screen lock while provisioning
powercfg /hibernate off
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0
# no automatic device encryption (Win11 without TPM never triggers it, but be explicit)
New-Item -Path HKLM:\SYSTEM\CurrentControlSet\Control\BitLocker -Force | Out-Null
Set-ItemProperty -Path HKLM:\SYSTEM\CurrentControlSet\Control\BitLocker -Name PreventDeviceEncryption -Value 1 -Type DWord
# Server Manager does not pop up at logon
if (Get-ScheduledTask -TaskName ServerManager -ErrorAction SilentlyContinue) {
    Disable-ScheduledTask -TaskName ServerManager -TaskPath '\Microsoft\Windows\Server Manager\' | Out-Null
}
