# Applies services.mssql of the host (and the sa login) by T-SQL. Every statement checks first and
# prints GOAD_CHANGED only when it changes something, so a second run reports no change.
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

function Invoke-Sql([string]$Query) {
    $out = & SqlCmd -S 127.0.0.1,1433 -E -b -Q $Query 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SqlCmd failed ($LASTEXITCODE): $out" }
    if ($out -match 'GOAD_CHANGED') { $Ansible.Changed = $true }
}
function Lit([string]$s) { $s.Replace("'", "''") }      # inside N'...'
function Ident([string]$s) { $s.Replace(']', ']]') }     # inside [...]

function Add-WindowsLogin([string]$Name) {
    # SQL logins (sa) exist already; a NETBIOS\name principal gets a Windows login
    if (-not $Name.Contains('\')) { return }
    Invoke-Sql "IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'$(Lit $Name)') BEGIN CREATE LOGIN [$(Ident $Name)] FROM WINDOWS; PRINT 'GOAD_CHANGED' END"
}

Invoke-Sql "IF EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = N'sa' AND (is_disabled = 1 OR PWDCOMPARE(N'$(Lit $SaPassword)', password_hash) = 0)) BEGIN ALTER LOGIN sa WITH PASSWORD = N'$(Lit $SaPassword)', CHECK_POLICY = OFF; ALTER LOGIN sa ENABLE; PRINT 'GOAD_CHANGED' END"

foreach ($p in $Sysadmins) {
    Add-WindowsLogin $p
    Invoke-Sql "IF NOT EXISTS (SELECT 1 FROM sys.server_role_members rm JOIN sys.server_principals r ON rm.role_principal_id = r.principal_id JOIN sys.server_principals m ON rm.member_principal_id = m.principal_id WHERE r.name = 'sysadmin' AND m.name = N'$(Lit $p)') BEGIN ALTER SERVER ROLE sysadmin ADD MEMBER [$(Ident $p)]; PRINT 'GOAD_CHANGED' END"
}

foreach ($i in $ImpersonateLogin) {
    Add-WindowsLogin $i.grantee
    Invoke-Sql "IF NOT EXISTS (SELECT 1 FROM sys.server_permissions p JOIN sys.server_principals g ON p.grantee_principal_id = g.principal_id JOIN sys.server_principals t ON p.major_id = t.principal_id WHERE p.class = 101 AND p.permission_name = 'IMPERSONATE' AND g.name = N'$(Lit $i.grantee)' AND t.name = N'$(Lit $i.login)') BEGIN GRANT IMPERSONATE ON LOGIN::[$(Ident $i.login)] TO [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
}

foreach ($i in $ImpersonateUser) {
    $db = Ident $i.database
    Add-WindowsLogin $i.grantee
    Invoke-Sql "USE [$db]; IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(Lit $i.grantee)') BEGIN CREATE USER [$(Ident $i.grantee)] FOR LOGIN [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
    Invoke-Sql "USE [$db]; IF NOT EXISTS (SELECT 1 FROM sys.database_permissions p JOIN sys.database_principals g ON p.grantee_principal_id = g.principal_id WHERE p.class = 4 AND p.permission_name = 'IMPERSONATE' AND g.name = N'$(Lit $i.grantee)' AND p.major_id = USER_ID(N'$(Lit $i.user)')) BEGIN GRANT IMPERSONATE ON USER::[$(Ident $i.user)] TO [$(Ident $i.grantee)]; PRINT 'GOAD_CHANGED' END"
}

for ($n = 0; $n -lt $Linked.Count; $n++) {
    $l = $Linked[$n]
    $name = Lit $l.name
    Add-WindowsLogin $l.local_login
    Invoke-Sql "IF NOT EXISTS (SELECT 1 FROM sys.servers WHERE name = N'$name') BEGIN EXEC sp_addlinkedserver @server = N'$name', @srvproduct = N'', @provider = N'SQLOLEDB', @datasrc = N'$(Lit $LinkedSources[$n])'; EXEC sp_serveroption N'$name', 'rpc', 'true'; EXEC sp_serveroption N'$name', 'rpc out', 'true'; PRINT 'GOAD_CHANGED' END"
    Invoke-Sql "IF NOT EXISTS (SELECT 1 FROM sys.linked_logins l JOIN sys.servers s ON l.server_id = s.server_id JOIN sys.server_principals p ON l.local_principal_id = p.principal_id WHERE s.name = N'$name' AND p.name = N'$(Lit $l.local_login)') BEGIN EXEC sp_addlinkedsrvlogin @rmtsrvname = N'$name', @locallogin = N'$(Lit $l.local_login)', @useself = N'False', @rmtuser = N'$(Lit $l.remote_login)', @rmtpassword = N'$(Lit $RemotePassword)'; PRINT 'GOAD_CHANGED' END"
}
