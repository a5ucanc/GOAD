# GOAD-Base

Hardened variant of GOAD: sevenkingdoms.local, north.sevenkingdoms.local (child domain) and essos.local (forest trust), with DC01 kingslanding, DC02 winterfell, DC03 meereen, SRV02 castelblack and SRV03 braavos (CAs: kingslanding and braavos).

No intentional vulnerabilities: no ACL abuses, SPNs, delegation, ADCS vulnerable templates or web enrollment, no MSSQL links or impersonation. Every account and local admin password is `Aa1234567890!`.
Hardening is applied by `hardening.yml` from `base_settings` in `data/config.json`. Vulnerabilities are added back through scenarios (`capabilities`).