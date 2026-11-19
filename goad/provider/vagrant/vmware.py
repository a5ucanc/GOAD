import os
from goad.log import Log
from goad.provider.vagrant.vagrant import VagrantProvider
from goad.utils import *


class VmwareProvider(VagrantProvider):
    provider_name = VMWARE
    default_provisioner = PROVISIONING_LOCAL
    allowed_provisioners = [PROVISIONING_LOCAL, PROVISIONING_RUNNER, PROVISIONING_DOCKER, PROVISIONING_VM]

    def supports_named_snapshots(self):
        return True

    def _vmx(self, vm):
        id_file = os.path.join(self.path, '.vagrant', 'machines', vm, 'vmware_desktop', 'id')
        if not os.path.isfile(id_file):
            return None
        with open(id_file) as f:
            return f.read().strip()

    def snapshot_restore(self, name, vms):
        # `vagrant snapshot restore` waits for WinRM as the vagrant user (even with --no-start it
        # halts the VM through the guest), which hangs once disable_vagrant ran: use vmrun.
        paths = self._snapshot_paths()
        for vm in vms:
            vmx = self._vmx(vm)
            if vmx is None:
                Log.error(f'no VMware machine id for {vm}')
                return False
            snapshot = paths.get(vm, {}).get(name, name)
            if not self.command.run_vmrun(['-T', 'ws', 'revertToSnapshot', vmx, snapshot], self.path):
                return False
            if not self.command.run_vmrun(['-T', 'ws', 'start', vmx, 'nogui'], self.path):
                return False
        return True

    def check(self):
        checks = [
            super().check(),
            self.command.check_vmware(),
            self.command.check_vmware_utility(),
            self.command.check_vagrant_plugin('vagrant-vmware-desktop', True)
        ]
        return all(checks)
