#!/bin/bash

# Install git and python3
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pip git

# git clone goad
GOAD_REPO=/home/vagrant/GOAD
GIT_FOLDER=$GOAD_REPO/.git
if [ ! -d $GIT_FOLDER ]
then
    rm -rf $GOAD_REPO
    git clone https://github.com/Orange-Cyberdefense/GOAD.git $GOAD_REPO
    cd $GOAD_REPO
    # git checkout -b v3-beta origin/v3-beta
else
    cd $GOAD_REPO
    git pull
fi

# Install ansible and pywinrm
python3 -m pip install --upgrade pip
cd $GOAD_REPO
python3 -m pip install -r requirements.yml

cd $GOAD_REPO/ansible
# galaxy.ansible.com is flaky : retry, and fail loudly (a missing collection breaks every playbook later)
galaxy_ok=0
for i in 1 2 3 4 5; do
    if /home/vagrant/.local/bin/ansible-galaxy install -r requirements.yml; then
        galaxy_ok=1
        break
    fi
    echo "[-] ansible-galaxy install failed (try $i/5), retry in 30s"
    sleep 30
done
if [ $galaxy_ok -ne 1 ]; then
    echo "[-] ansible-galaxy install -r requirements.yml failed 5 times, the provisioning will not work"
    exit 1
fi
/home/vagrant/.local/bin/ansible-galaxy collection list

# set color
sudo sed -i '/force_color_prompt=yes/s/^#//g' /home/*/.bashrc
sudo sed -i '/force_color_prompt=yes/s/^#//g' /root/.bashrc