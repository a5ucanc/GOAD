# GOAD-Mini-Base

Hardened variant of GOAD-Mini: only the sevenkingdoms.local domain and the kingslanding DC (also the CA).

No intentional vulnerabilities: no ACL abuses, SPNs, ADCS vulnerable templates or web enrollment. Every account and local admin password is `Aa1234567890!`.
Hardening is applied by `hardening.yml` from `base_settings` in `data/config.json`. Vulnerabilities are added back through scenarios (`capabilities`).
