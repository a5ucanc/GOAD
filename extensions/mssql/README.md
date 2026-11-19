# mssql extension

Installs SQL Server Express 2019 on the existing member servers of a Base lab. No new VM.

| Lab | Hosts | Capabilities granted |
|-----|-------|----------------------|
| GOAD-Base | srv02 castelblack (north), srv03 braavos (essos) | `mssql: [srv02, srv03]`, `mssql_link: [srv02]` |
| GOAD-Light-Base | srv02 castelblack (north) | `mssql: [srv02]` |

SSMS is installed on castelblack. The extension creates the service account `sql_svc` (password `Aa1234567890!`, no SPN) in each domain that gets a SQL Server, enables `sa` with `Aa1234567890!` and makes only the domain `Administrator` sysadmin. It adds no impersonation, no linked servers and no low-privileged sysadmins: the `mssql-*` scenarios add those.

    install_extension mssql
    remove_extension mssql

`remove_extension mssql` first disables every enabled scenario that needs the `mssql` or `mssql_link` capability (it lists them and asks, `--yes` skips the question), then runs `uninstall.yml`: uninstalls SSMS and SQL Server, removes the MSSQL firewall rules, removes `sql_svc` from Log on as a service, deletes `c:\setup\mssql` and the `sql_svc` users.

Not undone: the WinRM `MaxMemoryPerShellMB` quota the `mssql` role raises to 4096 for SQL Server setup.
