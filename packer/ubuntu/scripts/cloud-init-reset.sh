#!/bin/bash
# Clones configure themselves from guestinfo.metadata/userdata through cloud-init's VMware datasource.
set -euo pipefail
# the installer disables cloud-init networking and pins the datasource: undo both
rm -f /etc/cloud/cloud.cfg.d/subiquity-disable-cloudinit-networking.cfg \
      /etc/cloud/cloud.cfg.d/99-installer.cfg \
      /etc/cloud/cloud.cfg.d/90-installer-network.cfg \
      /etc/netplan/00-installer-config.yaml \
      /etc/netplan/50-cloud-init.yaml
cat > /etc/cloud/cloud.cfg.d/99-goad-vmware.cfg <<'CFG'
datasource_list: [ VMware, None ]
CFG
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
rm -f /etc/ssh/ssh_host_*
cloud-init clean --logs --seed
