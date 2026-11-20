#!/bin/bash
# Every .cer/.crt uploaded from goad's ca_certs_dir goes into the system trust store (PEM, .crt).
set -euo pipefail
shopt -s nullglob nocaseglob
count=0
for cert in /tmp/goad-ca/*.cer /tmp/goad-ca/*.crt; do
    name=$(basename "${cert%.*}")
    if grep -q 'BEGIN CERTIFICATE' "$cert"; then
        cp "$cert" "/usr/local/share/ca-certificates/goad-$name.crt"
    else
        openssl x509 -inform der -in "$cert" -out "/usr/local/share/ca-certificates/goad-$name.crt"
    fi
    count=$((count + 1))
done
update-ca-certificates
echo "$count certificate(s) imported"
rm -rf /tmp/goad-ca
