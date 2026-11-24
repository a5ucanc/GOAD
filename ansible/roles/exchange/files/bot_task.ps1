# Schedule readMail.ps1 every minute as the bot user, as main's botScheduler.ps1 did. Registered once:
# a task with the same action is left alone. Failures are reported in result.error without the password.
param([string]$User, [string]$Password, [string]$Script)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
try {
    $taskName = 'exchange_bot'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    # UserId may hold the bare user name: compare without the domain
    if ($task -and ($task.Principal.UserId -replace '^.*\\', '') -eq ($User -replace '^.*\\', '') -and
        $task.Actions[0].Arguments -eq $arguments) { return }
    if ($task) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable -DontStopOnIdleEnd -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -User $User -Password $Password `
        -Settings $settings | Out-Null
    $Ansible.Changed = $true
} catch {
    $Ansible.Result = @{ error = "exchange_bot task for ${User}: $($_.Exception.Message)" }
    $Ansible.Failed = $true
}
