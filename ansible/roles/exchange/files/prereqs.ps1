# The prerequisite packages not installed yet, by their uninstall entries.
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
$entries = Get-ChildItem -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                                'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' -ErrorAction SilentlyContinue |
    ForEach-Object { [pscustomobject]@{ Key = $_.PSChildName; Name = [string]$_.GetValue('DisplayName') } }
$wanted = [ordered]@{
    vcredist2012 = { $_.Name -like 'Microsoft Visual C++ 2012 x64*Runtime*' }
    vcredist2013 = { $_.Name -like 'Microsoft Visual C++ 2013 x64*Runtime*' }
    rewrite      = { $_.Name -like 'IIS URL Rewrite Module 2*' }
    ucma         = { $_.Key -eq 'UCMA4' -or $_.Name -like '*Unified Communications Managed API 4.0*' }
}
$missing = @(foreach ($name in $wanted.Keys) {
    if (-not ($entries | Where-Object $wanted[$name])) { $name }
})
$Ansible.Result = @{ missing = $missing }
