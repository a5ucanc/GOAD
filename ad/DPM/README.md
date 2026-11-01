# DPM

A small Active Directory lab built around **System Center Data Protection Manager (DPM) 2022**.
## Hosts

| Host  | Name      | IP            | Role                                                        | Box                         |
|-------|-----------|---------------|-------------------------------------------------------------|-----------------------------|
| dc01  | DC        | `{ip}.10`     | Domain controller for `dpm.lab` (NetBIOS `DPMLAB`)          | `mayfly/windows_server2019` |
| srv01 | DPM       | `{ip}.11`     | DPM 2022 server + local SQL Server 2022 (engine, SSRS, SSMS)| `mayfly/windows_server2019` |
| srv02 | PROTECTED | `{ip}.12`     | Member server, Finance share, DPM protection agent          | `mayfly/windows_server2019` |

DPM 2022 is supported on Windows Server 2019/2022 (not 2025), with SQL Server 2022 as the database. SQL is
co-located on the DPM server because DPM cannot run on a domain controller and the lab has no separate SQL
host. The DPM server needs ~8 GB RAM; it is provisioned with 4 vCPU / 8 GB.

## Credentials

| User      | Password              | Notes                                              |
|-----------|-----------------------|----------------------------------------------------|
| alice     | `whiteRabbit`         | Domain Admin                                       |
| bob       | `marley`              | Helpdesk, manages groups (`LocalAdmins`)           |
| carlos    | `Summer2024`          | Member of `DPM-Admins` — **local admin on DPM**    |
| dave      | `dragon`              | Low-privilege user                                 |
| dpm-sql   | `Dpm_SQL_SvcAcc0unt!` | SQL service account for the DPM database           |

Weak passwords, plaintext credentials and a readable Finance share are intentional — this is a deliberately
vulnerable lab.

## Deploy

```bash
python3 goad.py -t install -l DPM -p vmware
```

or interactively: `set_lab DPM`, `set_provider vmware`, then `install`.

The playbook order is defined in `playbooks.yml` under `DPM:`. SQL Server 2022 + Reporting Services + SSMS
are installed by `servers.yml` (the DPM host is in the `[mssql]`, `[mssql_reporting]` and `[mssql_ssms]`
groups) before `dpm-install.yml` installs DPM itself. `dpm-agent.yml` installs the protection agent on
PROTECTED, and `dpm-config.yml` attaches it, adds a backup storage volume and creates a protection group.

`dpm-install.yml` follows the official unattended install
(https://learn.microsoft.com/system-center/dpm/install-dpm?view=sc-dpm-2022#run-an-unattended-install):

- SQL Server, SQL Server Agent and Reporting Services run under one dedicated domain account (`dpm-sql`,
  local admin on the DPM host). The agent account must be in NetBIOS form (`DPMLAB\dpm-sql`): DPM makes it
  the owner of its SQL Agent jobs and setup fails with `DatabaseCreateFailed` (msdb error 14234) otherwise.
- Reporting Services is configured before setup (service account, `ReportServer` database, URLs).
- the `DPM_SqlServr.exe` / `DPM_UDP_Port_1434` firewall rules from the doc are added.
- the Hyper-V role and its PowerShell module (setup prerequisite check `HyperVPowerShell`) are enabled with
  the `dism.exe` command setup gives, then the host is rebooted.
- `DPMSetup.ini` is the doc template filled with NetBIOS names (no `ProductKey`: evaluation), and setup runs
  with `start /wait Setup.exe /i /f DPMSetup.ini /l dpmlog.txt`.
- success is checked on `HKLM\SOFTWARE\Microsoft\Microsoft Data Protection Manager\Setup\SetupSucceeded`; the
  leftovers of a failed setup (msi product, `DPMDB_DPM` database, registry) are removed before a new attempt.

## Notes and known limitations

- **Download links rot.** The DPM 2022 evaluation media and the SQL Server Native Client are pinned in the
  role defaults (`ansible/roles/dpm/install/dpm/defaults/main.yml` and
  `ansible/roles/dpm/install/sqlncli/defaults/main.yml`). If a download step fails, refresh the link there,
  or drop the installer in `C:\setup\dpm\` on the DPM host and re-run `provision dpm-install.yml`.
- **SQLNCLI is required.** SQL Server 2022 does not ship the SQL Server Native Client, which DPM 2022 RTM
  setup needs; it is installed separately on the DPM host before DPM.
- **DPM media extraction** uses silent InnoSetup switches. If extraction fails, extract the installer into
  `C:\setup\dpm\media\` manually (so `media\Setup.exe` exists) and re-run `provision dpm-install.yml`.
- **Backup storage.** DPM needs a volume on a basic, non-system disk (a locally created VHDX is not
  supported). The vmware provider gives the DPM VM a 60 GB data disk (`:disks` in its Vagrantfile);
  `dpm-config.yml` initializes it as `S:` and adds it to the DPM pool with `Add-DPMDiskStorage -Volume`.
- Only the **vmware** provider is provided for this lab.
