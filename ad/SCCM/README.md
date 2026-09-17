# SCCM lab

![SCCM overview](../../docs/img/SCCMLAB_overview.png)

## Servers
4 virtual machines with Windows Server 2019

- **DC** :  Domain Controler 
- **MECM** : mecm primary site serer
- **MSSQL** : mecm sql server
- **CLIENT** : mecm client computer

All vms got defender activated

## Software versions (checked against Microsoft docs, 2026-09)
| Component | Version installed | Compatibility |
|-----------|-------------------|---------------|
| Windows Server 2019 (all vms) | vagrant box `mayfly/windows_server2019` | supported site system / site database OS |
| SQL Server 2022 Evaluation | `SQL2022-SSEI-Eval.exe` (default instance, static port 1433) | supported since ConfigMgr 2303 |
| Configuration Manager | evaluation baseline from the eval center fwlink (currently **2403**, 180 days eval) | out of support since 2025-10 but the only baseline with a direct download ; 2509 eval needs a registration form |
| Windows ADK + WinPE add-on | **10.1.26100.2454 (December 2024)** | supported by ConfigMgr 2403, 2503, 2509 and 2603 (ADK 2004 is end of support) |
| ODBC Driver 18 for SQL Server | 18.3.3.1 + the `msodbcsql.msi` shipped in the baseline redist folder | ConfigMgr 2503+ requires 18.4.1.1+, never 18.6.1.1 / 18.7.1.1 |
| Visual C++ 2015-2022 Redistributable | latest (`aka.ms/vs/17/release/vc_redist.x64.exe`) | required by the ODBC driver and the site server |
| SQL Server Management Studio | 22 (`vs_SSMS.exe`) | supported on Windows Server 2019 |
| WSUS | Windows Server 2019 role, database on the remote SQL Server | software update point prerequisite |

Versions and download links are set in `ansible/roles/sccm/install/*/defaults/main.yml`.
If you change the Configuration Manager baseline, check the ADK / ODBC support matrix :
- https://learn.microsoft.com/en-us/intune/configmgr/core/plan-design/configs/support-for-windows-adk
- https://learn.microsoft.com/en-us/intune/configmgr/core/servers/deploy/install/list-of-prerequisite-checks

## Prerequisites
- The prerequisites for the lab are the same as GOAD lab (virtualbox/vmware, python, ansible,...)
- The lab take 16GB for the vagrant image + 100GB for the 4 vms (22GB of RAM : DC 4GB, MECM 8GB, MSSQL 6GB, CLIENT 4GB)
- The installation take environ 2,5 hours (with fiber connection)
- The lab download multiple files during the install (windows iso, mecm installation package, mssql installation package, ...), be sure to have a good internet connection.

## proxmox installation
- In order to use the proxmox provider follow this :

1) create a template with the windows_server2019_proxmox_cloudinit_uptodate.pkvars.hcl packer file (guide here: https://mayfly277.github.io/posts/GOAD-on-proxmox-part2-packer/) (note the id after the creation)

2) create the variable file (ad/SCCM/providers/proxmox/terraform/variables.tf) by coping the template (ad/SCCM/providers/proxmox/terraform/variables.tf.template) and change the value according to your proxmox environnement

3) on the provisioning computer :
```bash
./goad.sh -t check -l SCCM -p proxmox -m local
./goad.sh -t install -l SCCM -p proxmox -m local
```

4) if something goes wrong (restart of the vms during install, etc...), you can rerun only ansible with -a
```bash
./goad.sh -t install -l SCCM -p proxmox -m local -a
```