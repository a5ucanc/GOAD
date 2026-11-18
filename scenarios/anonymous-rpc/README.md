# anonymous-rpc

Adds two inheritable ACEs for `NT AUTHORITY\ANONYMOUS LOGON` on the domain root: `ReadProperty` and `GenericExecute` (as the GOAD north domain). This allows anonymous user and group enumeration over RPC (SAMR/LSA). It does not allow anonymous LDAP search: that also needs `dsHeuristics`, which the scenario does not change.

Attack:

    rpcclient -U '' -N <dc ip> -c 'enumdomusers'
    nxc smb <dc ip> -u '' -p '' --users

How to verify:

    dacledit.py -action read -principal 'ANONYMOUS LOGON' -target-dn '<domain DN>' <domain>/<user>:'Aa1234567890!' -dc-ip <dc ip>

Disable removes exactly those two explicit ACEs.
