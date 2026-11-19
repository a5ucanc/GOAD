# iis extension

Installs IIS on srv02 castelblack of GOAD-Base or GOAD-Light-Base. No new VM. Grants the `iis` capability on srv02, which the `iis-upload` scenario needs.

    install_extension iis
    remove_extension iis

The install runs the `iis` role (web server, management tools, IIS 6 compatibility, default `index.html`).

`remove_extension iis` first disables the enabled scenarios that need the `iis` capability (it lists them and asks, `--yes` skips the question), then runs `uninstall.yml`: removes the IIS features the role added, reboots when Windows asks for it, and deletes `C:\inetpub`.

Not undone: the Windows Update service the `iis` role starts, and the SYSTEM FullControl ACE the role adds on `C:\ProgramData\Microsoft\Crypto\RSA\MachineKeys`.
