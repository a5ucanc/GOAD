# Applies services.mssql of the host (and the sa login) by T-SQL. Every statement checks first and
# prints GOAD_CHANGED only when it changes something, so a second run reports no change.
# The task runs with no_log (passwords): a failure goes to $Ansible.Result.error, naming the step and,
# for statements without a password, the SqlCmd output. The role raises it in a task that logs.
param(
    [string]$SaPassword,
    [string[]]$Sysadmins = @(),
    [object[]]$ImpersonateLogin = @(),
    [object[]]$ImpersonateUser = @(),
    [object[]]$Linked = @(),
    [string[]]$LinkedSources = @(),
    [string]$RemotePassword
)
$ErrorActionPreference = 'Stop'
$Ansible.Changed = $false
# sqlcmd is on the machine PATH that setup wrote; read it again in case this process predates it
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine')

function Invoke-Sql([string]$Step, [string]$Query, [switch]$Secret) {
    # resolve sqlcmd first: a missing one must not pass on a stale $LASTEXITCODE
    $sqlcmd = Get-Command SqlCmd.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $sqlcmd) { throw "mssql step '$Step' failed: SqlCmd.exe not found on the machine PATH" }
    # Continue: PowerShell 5.1 turns redirected native stderr into an error record, which Stop would throw
    # before the exit code check (and past the Secret withholding)
    $ErrorActionPreference = 'Continue'
    $out = & $sqlcmd.Source -S 127.0.0.1,1433 -E -b -Q $Query 2>&1
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) {
        $detail = if ($Secret) { '(output withheld: the statement holds a password)' } else { "$out" }
        throw ("mssql step '$Step' failed (SqlCmd exit $LASTEXITCODE): $detail")
    }
    if ($out -match 'GOAD_CHANGED') { $Ansible.Changed = $true }
}
function Lit([string]$s) { $s.Replace("'", "''") }      # inside N'...'
function Ident([string]$s) { $s.Replace(']', ']]') }     # inside [...]

function Add-WindowsLogin([string]$Name) {
    # SQL logins (sa) exist already; a NETBIOS\name principal gets a Windows login
    if (-not $Name.Contains('\')) { return }
    Invoke-Sql "login $Name" "IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'$(Lit $Name)') BEGIN CREATE LOGIN [$(Ident $Name)] FROM WINDOWS; PRINT 'GOAD_CHANGED' END"
}

try {
    Invoke-Sql 'sa login' -Secret "IF EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = N'sa' AND (is_disabled = 1 OR PWDCOMPARE(N'$(Lit $SaPassword)', password_hash) = 0)) BEGIN ALTER LOGIN sa WITH PASSWORD = N'$(Lit $SaPassword)', CHECK_POLICY = OFF; ALTER LOGIN sa ENABLE; PRINT 'GOAD_CHANGED' END"

    foreach ($p in $Sysadmins) {
        Add-WindowsLogin $p
        Invoke-Sql "sysadmin $p" "IF NOT EXISTS (SELECT 1 FROM sys.server_role_members rm JOIN sys.server_principals r ON rm.role_principal_id = r.principal_id JOIN sys.server_principals m ON rm.member_principal_id = m.principal_id WHERE r.name = 'sysadmin' AND m.name = N'$(Lit $p)') BEGIN ALTER SERVER ROLE sysadmin ADD MEMBER [$(Ident $p)]; PRINT 'GOAD_CHANGED' END"
    }

    foreach ($i in $ImpersonateLogin) {
        Add-WindowsLogin $i.grantee
        Invoke-Sql "impersonate login $($i.login) for $($i.grantee)" "IF NOT EXISTS (SELECT 1 FROM sys.server_permissions p JOIN sys.server_principals g ON p.grantee_principal_id = g.principal_id JOIN sys.server_principals t ON p.major_id = t.principal_id WHERE p.class = 101 AND p.permission_name = 'IMPERSONATE' AND g.name = N'$(Lit $i.grantee)' AND t.name = N'$(Lit $i.login)') BEGIN GRANT IMPERSONATE ON LOGIN::[$(Ident $i.login)] TO [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
    }

    foreach ($i in $ImpersonateUser) {
        $db = Ident $i.database
        Add-WindowsLogin $i.grantee
        Invoke-Sql "database user $($i.grantee) in $($i.database)" "USE [$db]; IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(Lit $i.grantee)') BEGIN CREATE USER [$(Ident $i.grantee)] FOR LOGIN [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
        Invoke-Sql "impersonate user $($i.user) for $($i.grantee) in $($i.database)" "USE [$db]; IF NOT EXISTS (SELECT 1 FROM sys.database_permissions p JOIN sys.database_principals g ON p.grantee_principal_id = g.principal_id WHERE p.class = 4 AND p.permission_name = 'IMPERSONATE' AND g.name = N'$(Lit $i.grantee)' AND p.major_id = USER_ID(N'$(Lit $i.user)')) BEGIN GRANT IMPERSONATE ON USER::[$(Ident $i.user)] TO [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
    }

    for ($n = 0; $n -lt $Linked.Count; $n++) {
        $l = $Linked[$n]
        $name = Lit $l.name
        Add-WindowsLogin $l.local_login
        Invoke-Sql "linked server $($l.name)" "IF NOT EXISTS (SELECT 1 FROM sys.servers WHERE name = N'$name') BEGIN EXEC sp_addlinkedserver @server = N'$name', @srvproduct = N'', @provider = N'SQLOLEDB', @datasrc = N'$(Lit $LinkedSources[$n])'; EXEC sp_serveroption N'$name', 'rpc', 'true'; EXEC sp_serveroption N'$name', 'rpc out', 'true'; PRINT 'GOAD_CHANGED' END"
        Invoke-Sql "linked login $($l.local_login) on $($l.name)" -Secret "IF NOT EXISTS (SELECT 1 FROM sys.linked_logins l JOIN sys.servers s ON l.server_id = s.server_id JOIN sys.server_principals p ON l.local_principal_id = p.principal_id WHERE s.name = N'$name' AND p.name = N'$(Lit $l.local_login)') BEGIN EXEC sp_addlinkedsrvlogin @rmtsrvname = N'$name', @locallogin = N'$(Lit $l.local_login)', @useself = N'False', @rmtuser = N'$(Lit $l.remote_login)', @rmtpassword = N'$(Lit $RemotePassword)'; PRINT 'GOAD_CHANGED' END"
    }
} catch {
    # Invoke-Sql throws a password-free 'mssql step ...' message; anything else (sqlcmd missing, bad
    # parameter) carries no statement text either
    $message = $_.Exception.Message
    if (-not $message.StartsWith('mssql step')) { $message = "mssql options failed: $message" }
    $Ansible.Result = @{ error = $message }
    $Ansible.Failed = $true
}
