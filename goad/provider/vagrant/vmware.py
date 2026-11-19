import os
import time
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

    @staticmethod
    def _norm(vmx):
        return vmx.strip().replace('\\', '/').lower()

    def running_vms(self):
        ok, output = self.command.run_vmrun_output(['-T', 'ws', 'list'], self.path)
        if not ok:
            return None
        running = {self._norm(line) for line in output.splitlines()[1:] if line.strip()}
        return [vm for vm in self.vm_names() if self._vmx(vm) and self._norm(self._vmx(vm)) in running]

    def boot_vms(self):
        # vmrun start does not log in to the guest, unlike vagrant up
        running = self.running_vms()
        if running is None:
            Log.error('vmrun list failed')
            return False
        failed = []
        for vm in self.vm_names():
            if vm in running:
                continue
            vmx = self._vmx(vm)
            if vmx is None or not self.command.run_vmrun(['-T', 'ws', 'start', vmx, 'nogui'], self.path):
                failed.append(vm)
        if failed:
            Log.error(f'vmrun start failed on {", ".join(failed)}')
        return not failed

    def wait_halted(self, vms, timeout=600, interval=10):
        # the guests shut themselves down: wait until VMware reports them off, then force the rest
        deadline = time.monotonic() + timeout
        left = list(vms)
        while True:
            running = self.running_vms()
            if running is not None:
                left = [vm for vm in vms if vm in running]
            if not left or time.monotonic() >= deadline:
                break
            time.sleep(interval)
        if not left:
            return True
        Log.warning(f'{", ".join(left)} still running after {timeout}s: forcing them off')
        failed = [vm for vm in left if not self.command.run_vmrun(['-T', 'ws', 'stop', self._vmx(vm), 'hard'], self.path)]
        if failed:
            Log.error(f'vmrun stop failed on {", ".join(failed)}')
        return not failed

    def snapshot_restore(self, name, vms):
        # `vagrant snapshot restore` waits for WinRM as the vagrant user (even with --no-start it
        # halts the VM through the guest), which hangs once disable_vagrant ran: use vmrun.
        # every VM is attempted: stopping at the first failure would leave a mixed lab silently
        paths = self._snapshot_paths()
        failed = []
        for vm in vms:
            vmx = self._vmx(vm)
            snapshot = paths.get(vm, {}).get(name, name)
            if vmx is None:
                Log.error(f'no VMware machine id for {vm}')
                failed.append(vm)
            elif not (self.command.run_vmrun(['-T', 'ws', 'revertToSnapshot', vmx, snapshot], self.path)
                      and self.command.run_vmrun(['-T', 'ws', 'start', vmx, 'nogui'], self.path)):
                failed.append(vm)
        if failed:
            reverted = [vm for vm in vms if vm not in failed]
            Log.error(f'restore of {name} failed on {", ".join(failed)}; reverted: {", ".join(reverted) or "none"}')
        return not failed

    def check(self):
        checks = [
            super().check(),
            self.command.check_vmware(),
            self.command.check_vmware_utility(),
            self.command.check_vagrant_plugin('vagrant-vmware-desktop', True)
        ]
        return all(checks)
