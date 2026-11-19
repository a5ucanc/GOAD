# GOAD-Base

Hardened variant of GOAD: sevenkingdoms.local, north.sevenkingdoms.local (child domain) and essos.local (forest trust), with DC01 kingslanding, DC02 winterfell, DC03 meereen, SRV02 castelblack and SRV03 braavos (CAs: kingslanding and braavos).

No intentional vulnerabilities: no ACL abuses, SPNs, delegation, ADCS vulnerable templates or web enrollment. Every account and local admin password is `Aa1234567890!`.
Hardening is applied by `hardening.yml` from `base_settings` in `data/config.json`. Vulnerabilities are added back through scenarios (`capabilities`).

No services: MSSQL and IIS come from the `mssql` and `iis` extensions (`install_extension mssql`, `install_extension iis`). The `mssql-*` and `iis-upload` scenarios need them.
