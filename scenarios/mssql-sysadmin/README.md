# mssql-sysadmin

Creates domain user `scn-sql-admin` (password `Aa1234567890!`) with a sysadmin login on the target SQL Server. Commands run through `xp_cmdshell` as the SQL service account, which holds `SeImpersonatePrivilege` (potato to SYSTEM).

Attack:

    mssqlclient.py -windows-auth <domain>/scn-sql-admin:'Aa1234567890!'@<host ip>
    SQL> enable_xp_cmdshell
    SQL> xp_cmdshell whoami /priv

How to verify:

    SELECT IS_SRVROLEMEMBER('sysadmin', 'NB\scn-sql-admin')   # 1

Disable gives databases owned by the login back to `sa`, closes its sessions, drops the login and resets `xp_cmdshell` and `show advanced options` to `0` (Base values), and deletes the domain user. Not cleaned: changes made with sysadmin rights (other logins, jobs).
