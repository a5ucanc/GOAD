import os
from jinja2 import Environment, FileSystemLoader
from goad.goadpath import GoadPath
from goad.provider.provider import Provider
from goad.vagrant_names import vm_names_in


class VagrantProvider(Provider):

    def __init__(self, lab_name):
        super().__init__(lab_name)
        self.jumpbox_setup_script = 'setup_local_jumpbox.sh'
        # VagrantGate set by the instance: runs the vagrant commands that log in to the guests
        # with the vagrant account enabled when a base lab disabled it
        self.vagrant_gate = None

    def set_vagrant_gate(self, gate):
        self.vagrant_gate = gate

    def _guest_login(self, args, redisable=True):
        def command():
            return self.command.run_vagrant(args, self.path)
        if self.vagrant_gate is None:
            return command()
        return self.vagrant_gate.run(command, redisable=redisable)

    def _halt(self, vms, args):
        if self.vagrant_gate is not None and self.vagrant_gate.disabled():
            # halting through vagrant would leave the account enabled on VMs that are off
            halted = self.vagrant_gate.halt(vms)
            if halted is not None:
                return halted
        return self._guest_login(args, redisable=False)

    def running_vms(self):
        """Lab VMs running now, read without vagrant; None when the provider cannot tell."""
        return None

    def wait_halted(self, vms, timeout=600, interval=10):
        """Wait for the VMs to power off after a guest shutdown, force the rest off."""
        raise NotImplementedError

    def boot_vms(self):
        """Start the lab VMs without vagrant (no guest login). The base class cannot: it returns
        True and the enable playbook fails on the VMs that are off."""
        return True

    def check(self):
        checks = [
            self.command.check_vagrant(),
            self.command.check_disk(),
            self.command.check_ram(),
            self.command.check_ansible(),
            self.command.check_vagrant_plugin('vagrant-reload')
        ]
        return all(checks)

    def install(self):
        return self._guest_login(['up'])

    def destroy(self):
        return self.command.run_vagrant(['destroy'], self.path)

    def start(self):
        return self._guest_login(['up'])

    def stop(self):
        return self._halt(self.vm_names(), ['halt'])

    def status(self):
        return self.command.run_vagrant(['status'], self.path)

    def snapshot(self):
        return self.command.run_vagrant(['snapshot', 'push'], self.path)

    def reset(self):
        return self._guest_login(['snapshot', 'pop', '--no-delete'])

    def destroy_vm(self, vm_name):
        return self.command.run_vagrant(['destroy', vm_name], self.path)

    def start_vm(self, vm_name):
        return self._guest_login(['up', vm_name])

    def stop_vm(self, vm_name):
        return self._halt([vm_name], ['halt', vm_name])

    def remove_extension(self, extension_name):
        # TODO one day if possible
        pass

    def get_jumpbox_ip(self, ip_range=''):
        return ip_range + '.3'

    def vm_names(self):
        with open(os.path.join(self.path, 'Vagrantfile')) as vagrantfile:
            return vm_names_in(vagrantfile.read())

    def snapshot_save(self, name):
        return self.command.run_vagrant(['snapshot', 'save', name], self.path)

    def _snapshot_paths(self):
        # machine-readable rows: <ts>,<vm>,ui,detail,<tree path>; a VM without snapshots has a
        # detail row of indented help text. The tree path is "parent/child"; vagrant-vmware-desktop
        # only finds a nested snapshot by that full path, so keep name -> path per VM.
        ok, output = self.command.run_vagrant_output(['snapshot', 'list', '--machine-readable'], self.path)
        paths = {}
        for line in output.splitlines():
            parts = line.split(',', 4)
            if len(parts) < 5:
                continue
            vm, kind, detail = parts[1], parts[2:4], parts[4]
            if kind == ['metadata', 'provider']:
                paths.setdefault(vm, {})
            elif kind == ['ui', 'detail'] and detail and not detail[0].isspace():
                paths.setdefault(vm, {})[detail.split('/')[-1]] = detail
        return paths

    def snapshot_list(self):
        return {vm: list(names) for vm, names in self._snapshot_paths().items()}

    def snapshot_restore(self, name, vms):
        paths = self._snapshot_paths()
        return all(self.command.run_vagrant(['snapshot', 'restore', '--no-provision', vm, paths.get(vm, {}).get(name, name)], self.path)
                   for vm in vms)

    def snapshot_delete(self, name, vms):
        paths = self._snapshot_paths()
        return all(self.command.run_vagrant(['snapshot', 'delete', vm, paths.get(vm, {}).get(name, name)], self.path)
                   for vm in vms)

    def destroy_vms(self, vms):
        return all(self.command.run_vagrant(['destroy', '-f', vm], self.path) for vm in vms)

    def extension_vm_names(self, extension_name, lab_name, ip_range):
        folder = GoadPath.get_extension_providers_provider_path(extension_name, self.provider_name)
        if not os.path.isfile(os.path.join(folder, 'Vagrantfile')):
            return []
        template = Environment(loader=FileSystemLoader(folder)).get_template('Vagrantfile')
        return vm_names_in(template.render(lab_name=lab_name, ip_range=ip_range))
