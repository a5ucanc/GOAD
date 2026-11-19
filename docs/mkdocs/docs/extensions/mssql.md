# mssql

- Extension name : `mssql`
- Description : Install SQL Server Express 2019 on the member servers of a `-Base` lab (no new VM)
- Compatibility  : GOAD-Base / GOAD-Light-Base
- Providers : every provider of the lab (no VM)

- Hosts : srv02 castelblack (SQL Server + SSMS), and srv03 braavos on GOAD-Base
- Capabilities : GOAD-Base `mssql: [srv02, srv03]`, `mssql_link: [srv02]`; GOAD-Light-Base `mssql: [srv02]`
- Accounts : `sa` / `Aa1234567890!`, service account `sql_svc` / `Aa1234567890!` (no SPN) in each domain with a SQL Server

No vulnerable settings: no impersonation, no linked servers, only the domain Administrator is sysadmin. The `mssql-*` scenarios add those.

```
install_extension mssql
remove_extension mssql
```

`remove_extension mssql` disables the enabled scenarios that need `mssql` or `mssql_link` (it asks first), then uninstalls SSMS and SQL Server, removes the MSSQL firewall rules and deletes `sql_svc`.
