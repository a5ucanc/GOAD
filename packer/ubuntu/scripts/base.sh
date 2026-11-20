#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y full-upgrade
apt-get -y install open-vm-tools ca-certificates openssl
apt-get -y autoremove --purge
apt-get clean
