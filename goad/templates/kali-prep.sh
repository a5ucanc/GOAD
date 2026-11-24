#!/bin/bash
# Prepares Kali's prebuilt VMware image as a goad template (goad template import kali).
# goad copies this file into the guest and runs it as kali, with that account's password as $1.
# Clones then configure themselves from guestinfo.metadata/userdata through cloud-init's VMware
# datasource, like ubuntu2404 clones (packer/ubuntu/scripts/cloud-init-reset.sh): hostname, the goad
# user's password, static IP on the lab NIC, SSH, and the guestinfo.goad.firstboot marker.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "${1:?usage: kali-prep.sh <password of the calling user>}" | sudo -S -p '' bash "$0"
    exit 0
fi

exec > >(tee -a /var/log/goad-kali-prep.log) 2>&1
echo "kali-prep.sh started $(date -u +%FT%TZ)"

# ca_certs_dir certificates goad copied in, as packer/ubuntu/scripts/import-ca.sh does for ubuntu2404
count=0
for cert in /tmp/goad-ca-*; do
    [ -f "$cert" ] || continue
    name=$(basename "${cert%.*}")
    if grep -q 'BEGIN CERTIFICATE' "$cert"; then
        cp "$cert" "/usr/local/share/ca-certificates/$name.crt"
    else
        openssl x509 -inform der -in "$cert" -out "/usr/local/share/ca-certificates/$name.crt"
    fi
    rm -f "$cert"
    count=$((count + 1))
done
mkdir -p /usr/local/share/ca-certificates
update-ca-certificates
echo "$count certificate(s) imported"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install cloud-init openssh-server open-vm-tools
apt-get clean

# goad's account on every Linux host: cloud-init sets its password per clone (chpasswd)
id goad >/dev/null 2>&1 || useradd -m -s /bin/bash goad
usermod -aG sudo goad
echo 'goad ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-goad
chmod 440 /etc/sudoers.d/90-goad

# Kali runs NetworkManager (no netplan): have cloud-init write and bring up NetworkManager profiles
cat > /etc/cloud/cloud.cfg.d/99-goad-vmware.cfg <<'CFG'
datasource_list: [ VMware, None ]
# /etc/hosts still names the image's hostname (kali): sudo would warn on every clone
manage_etc_hosts: true
system_info:
  network:
    renderers: [ network-manager ]
    activators: [ network-manager ]
CFG
# profiles saved by the image would compete with cloud-init's for the NICs
rm -f /etc/NetworkManager/system-connections/*

# the cloud-init package enables its own units; Kali ships sshd disabled
systemctl enable ssh

truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
rm -f /etc/ssh/ssh_host_*
cloud-init clean --logs --seed

echo "kali-prep.sh done $(date -u +%FT%TZ), powering off"
# poweroff a few seconds after this script exits, so vmrun runProgramInGuest sees exit code 0 first
systemd-run --on-active=15 /bin/systemctl poweroff
