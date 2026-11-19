# iis-upload

Needs the `iis` extension (`install_extension iis`).

Copies the GOAD upload application (`Default.aspx`, `Web.config`, `bin`, from `ad/GOAD/files/srv02/wwwroot`) to `C:\inetpub\wwwroot` on the IIS host and creates `C:\inetpub\wwwroot\upload` with `FullControl` for `IIS_IUSRS`. The Base `index.html` is not touched.

Attack:

    # upload an .aspx webshell through http://<host ip>/Default.aspx, then browse to /upload/<shell>.aspx
    # the shell runs as the app pool identity (SeImpersonatePrivilege): potato to SYSTEM

How to verify:

    curl -s http://<host ip>/Default.aspx | grep -i upload

Disable stops `DefaultAppPool` (it locks `bin\*.dll`), removes `Default.aspx`, `Web.config`, `bin` and `upload` (with any uploaded file), then starts the pool again.
