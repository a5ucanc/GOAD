from abc import ABC
from goad.command.cmd_factory import CommandFactory
from goad.utils import *


class Provider(ABC):
    lab_name = ''
    provider_name = None
    default_provisioner = PROVISIONING_LOCAL
    allowed_provisioners = ALLOWED_PROVISIONER
    update_ip_range = False

    def __init__(self, lab_name):
        self.lab_name = lab_name
        self.path = None
        self.command = CommandFactory.get_command()

    def set_instance_path(self, provider_instance_path):
        self.path = provider_instance_path

    def check(self):
        pass

    def install(self):
        pass

    def destroy(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def status(self):
        pass

    def start_vm(self, vm_name):
        pass

    def stop_vm(self, vm_name):
        pass

    def destroy_vm(self, vm_name):
        pass

    def get_jumpbox_ip(self, ip_range=''):
        return None

    def restart_vm(self, vm_name):
        self.stop_vm(vm_name)
        self.start_vm(vm_name)

    # named whole-lab snapshots: only providers that return True implement the methods below
    def supports_named_snapshots(self):
        return False

    def vm_names(self):
        raise NotImplementedError

    def snapshot_save(self, name):
        raise NotImplementedError

    def snapshot_list(self):
        raise NotImplementedError

    def snapshot_restore(self, name, vms):
        raise NotImplementedError

    def snapshot_delete(self, name, vms):
        raise NotImplementedError

    def destroy_vms(self, vms):
        raise NotImplementedError

    def extension_vm_names(self, extension_name, lab_name, ip_range):
        raise NotImplementedError
