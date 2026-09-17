import os.path

from goad.command.linux import LinuxCommand
from goad.command.wsl import WslCommand
from goad.log import Log
from goad.utils import *
from goad.goadpath import GoadPath
from goad.jumpbox import JumpBox


class LocalJumpBox(JumpBox):

    def __init__(self, instance, creation=False):
        super().__init__(instance, creation)
        self.username = 'vagrant'

    def provision(self):
        script_name = self.provider.jumpbox_setup_script
        script_file = GoadPath.get_script_file(script_name)
        if not os.path.isfile(script_file):
            Log.error(f'script file: {script_file} not found !')
            return None
        self.command.scp(script_file, f'{self.username}@{self.ip}:~/setup.sh', self.ssh_key, self.instance_path)
        if Utils.is_windows():
            # if is windows convert line ending
            self.run_command("sudo apt update && sudo apt install -y dos2unix", '~')
            self.run_command("dos2unix setup.sh", '~')
        result = self.run_command('bash setup.sh', '~')
        if not result:
            Log.error('jumpbox setup script failed (see errors above), the provisioning will probably fail')
        return result

    def install_requirements(self):
        """
        setup.sh installs the python and galaxy requirements of the upstream clone : reinstall them from the
        local (synced) requirements files so the jumpbox matches the repository being deployed
        """
        self.run_command('python3 -m pip install -q -r requirements.yml', '~/GOAD')
        return self.run_command('/home/vagrant/.local/bin/ansible-galaxy install --force -r requirements.yml', '~/GOAD/ansible')

    def get_jumpbox_key(self, creation=False):
        if not creation:
            # example : workspace/bf0c11-goad-light-vmware/provider/.vagrant/machines/ELK/vmware_desktop/private_key
            provider_folder = f'{self.instance_path}/provider/.vagrant/machines/PROVISIONING/'.replace('/', os.path.sep)
            provider_folders = Utils.list_folders(provider_folder)
            if len(provider_folders) > 0:
                return provider_folder + provider_folders[0] + os.path.sep + 'private_key'
            key_supposed_path = provider_folder + '<provider_name>' + os.path.sep + 'private_key'
            Log.error(f'PROVISIONING ssh key not found at : {key_supposed_path}')
        return None

    def sync_sources(self):
        """
        rsync ansible folder to the jumpbox ip
        local_vm got GOAD cloned from github in ~/GOAD, so we push the local ansible sources
        (ansible/, ad/<lab>/, extensions/, playbooks.yml) on top of it to keep local changes,
        then sync the workspace folder
        :return:
        """
        if Utils.is_valid_ipv4(self.ip):
            # Copy the globalsettings.ini file to the jumpbox
            self.command.scp(GoadPath.get_global_inventory_path(), f'{self.username}@{self.ip}:~/GOAD/globalsettings.ini', self.ssh_key, self.instance_path)
            # Copy the local provisioning sources (override the github clone with local changes)
            project_path = GoadPath.get_project_path()
            local_sources = [
                (project_path + 'ansible', '~/GOAD/'),
                (project_path + 'extensions', '~/GOAD/'),
                (project_path + 'playbooks.yml', '~/GOAD/playbooks.yml'),
                (project_path + 'scripts', '~/GOAD/'),
                (GoadPath.get_lab_path(self.lab_name), '~/GOAD/ad/'),
            ]
            for source, destination in local_sources:
                if os.path.exists(source):
                    self.command.scp(f'-r "{source}"', f'{self.username}@{self.ip}:{destination}', self.ssh_key, self.instance_path)
            if Utils.is_windows():
                # if is windows convert line ending of shell scripts
                self.run_command("find ~/GOAD/ansible ~/GOAD/extensions ~/GOAD/ad ~/GOAD/scripts -type f -name '*.sh' -exec dos2unix -q {} +", '~')
            # create workspace dir if not exist
            self.run_command('mkdir -p ~/GOAD/workspace/' + self.instance_id, '~')
            # workspace inventory files (no need -r as it will copy all the provider folder)
            for src_file in Utils.list_files(self.instance_path):
                source = self.instance_path + os.path.sep + src_file
                destination_file = f'~/GOAD/workspace/{self.instance_id}/{src_file}'
                destination = f'{self.username}@{self.ip}:{destination_file}'
                self.command.scp(source, destination, self.ssh_key, self.instance_path)
                if Utils.is_windows():
                    # if is windows convert line ending
                    self.run_command(f"dos2unix {destination_file}", '~')
        else:
            Log.error('Can not sync source jumpbox ip is invalid')
