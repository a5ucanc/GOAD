#!/bin/bash
# Every .cer/.crt uploaded from goad's ca_certs_dir goes into the system trust store (PEM, .crt).
set -euo pipefail
count=0
# the upload may land the folder's files directly in /tmp/goad-ca or one level deeper
[ -d /tmp/goad-ca ] || { echo '0 certificate(s) imported'; [ "${GOAD_CA_EXPECTED:-0}" = 1 ] && exit 1; exit 0; }
while IFS= read -r -d '' cert; do
    name=$(basename "${cert%.*}")
    if grep -q 'BEGIN CERTIFICATE' "$cert"; then
        cp "$cert" "/usr/local/share/ca-certificates/goad-$name.crt"
    else
        openssl x509 -inform der -in "$cert" -out "/usr/local/share/ca-certificates/goad-$name.crt"
    fi
    count=$((count + 1))
done < <(find /tmp/goad-ca -type f \( -iname '*.cer' -o -iname '*.crt' \) -print0)
update-ca-certificates
echo "$count certificate(s) imported"
if [ "${GOAD_CA_EXPECTED:-0}" = 1 ] && [ "$count" -eq 0 ]; then
    echo "ca_certs_dir is set but no certificate was found" >&2
    exit 1
fi
rm -rf /tmp/goad-ca
