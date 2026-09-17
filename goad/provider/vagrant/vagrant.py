from goad.provider.provider import Provider
from goad.log import Log


class VagrantProvider(Provider):

    def __init__(self, lab_name):
        super().__init__(lab_name)
        self.jumpbox_setup_script = 'setup_local_jumpbox.sh'

    def check(self):
        checks = [
            self.command.check_vagrant(),
            self.command.check_disk(),
            self.command.check_ram(),
            self.command.check_ansible(),
            self.command.check_vagrant_plugin('vagrant-reload')
        ]
        return all(checks)

    def install(self, tries=3):
        # a windows vm can miss the boot timeout on a slow first boot ("The box is not able to report an address for
        # WinRM to connect to yet") or crash a provisioner ("not ready for guest communication") : retry the up.
        # --provision is forced on the retries so a vm marked "already provisioned" by a crashed run gets its
        # provisioners (ConfigureRemotingForAnsible.ps1, fix_ip.ps1) run again.
        result = self.command.run_vagrant(['up'], self.path)
        nb_try = 1
        while not result and nb_try < tries:
            nb_try += 1
            Log.warning(f'vagrant up failed, retry {nb_try}/{tries} with --provision')
            result = self.command.run_vagrant(['up', '--provision'], self.path)
        return result

    def destroy(self):
        return self.command.run_vagrant(['destroy', '-f'], self.path)

    def start(self):
        return self.command.run_vagrant(['up'], self.path)

    def stop(self):
        return self.command.run_vagrant(['halt'], self.path)

    def status(self):
        return self.command.run_vagrant(['status'], self.path)

    def snapshot(self):
        return self.command.run_vagrant(['snapshot', 'push'], self.path)

    def reset(self):
        return self.command.run_vagrant(['snapshot', 'pop', '--no-delete'], self.path)

    def destroy_vm(self, vm_name):
        return self.command.run_vagrant(['destroy', vm_name], self.path)

    def start_vm(self, vm_name):
        return self.command.run_vagrant(['up', vm_name], self.path)

    def stop_vm(self, vm_name):
        return self.command.run_vagrant(['halt', vm_name], self.path)

    def remove_extension(self, extension_name):
        # TODO one day if possible
        pass

    def get_jumpbox_ip(self, ip_range=''):
        return ip_range + '.3'
