# Enable a mailbox for every enabled user of the domain that has none yet, as main's ludus_exchange did,
# then set the language and time zone of the mailboxes that have none (no first-logon splash screen in OWA).
param([string]$DomainDn, [string[]]$Exclude)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
Add-PSSnapin -Name Microsoft.Exchange.Management.PowerShell.SnapIn
$failed = @()
$created = @()
foreach ($user in Get-User -RecipientTypeDetails User -ResultSize Unlimited) {
    $sam = [string]$user.SamAccountName
    if (-not $user.DistinguishedName.EndsWith(",$DomainDn") -or $sam.EndsWith('$') -or $Exclude -contains $sam -or
        $sam -like 'SM_*' -or $sam -like 'HealthMailbox*' -or [string]$user.UserAccountControl -match 'AccountDisabled') {
        continue
    }
    try {
        Enable-Mailbox -Identity $user.DistinguishedName -ErrorAction Stop | Out-Null
        $created += $sam
    } catch {
        $failed += "${sam}: $($_.Exception.Message)"
    }
}
$configured = @()
foreach ($mailbox in Get-Mailbox -RecipientTypeDetails UserMailbox -ResultSize Unlimited) {
    try {
        if (-not (Get-MailboxRegionalConfiguration -Identity $mailbox.DistinguishedName -ErrorAction Stop).Language) {
            Set-MailboxRegionalConfiguration -Identity $mailbox.DistinguishedName -Language en-US `
                -TimeZone 'Romance Standard Time' -ErrorAction Stop
            $configured += [string]$mailbox.Alias
        }
    } catch {
        $failed += "$($mailbox.Alias) regional configuration: $($_.Exception.Message)"
    }
}
$Ansible.Changed = ($created.Count + $configured.Count) -gt 0
$Ansible.Result = @{ created = $created; configured = $configured }
if ($failed) { throw "mailbox setup failed for: $($failed -join '; ')" }
