# GOAD-Light-Base

Hardened variant of GOAD-Light: sevenkingdoms.local, north.sevenkingdoms.local (child domain), DC01 kingslanding (also the CA), DC02 winterfell and SRV02 castelblack (member server).

No intentional vulnerabilities: no ACL abuses, SPNs, delegation, ADCS vulnerable templates or web enrollment. Every account and local admin password is `Aa1234567890!`.
Hardening is applied by `hardening.yml` from `base_settings` in `data/config.json`. Vulnerabilities are added back through scenarios (`capabilities`).

No services: MSSQL and IIS come from the `mssql` and `iis` extensions (`install_extension mssql`, `install_extension iis`). The `mssql-*` and `iis-upload` scenarios need them; `mssql-linked` is not available on this lab.
