from goad.provider.vagrant.vagrant import VagrantProvider
from goad.utils import *


class VmwareProvider(VagrantProvider):
    provider_name = VMWARE
    default_provisioner = PROVISIONING_LOCAL
    allowed_provisioners = [PROVISIONING_LOCAL, PROVISIONING_RUNNER, PROVISIONING_DOCKER, PROVISIONING_VM]

    def supports_named_snapshots(self):
        return True

    def check(self):
        checks = [
            super().check(),
            self.command.check_vmware(),
            self.command.check_vmware_utility(),
            self.command.check_vagrant_plugin('vagrant-vmware-desktop', True)
        ]
        return all(checks)
