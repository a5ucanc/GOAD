from goad.log import Log


class VagrantGate:
    """Wraps the vagrant commands that log in to the guests as the vagrant user (up, halt, reload,
    snapshot pop/restore). Base labs disable that account after provisioning: without it vagrant
    waits for WinRM until it times out. When instance.json says the account is disabled, the gate
    boots the lab VMs outside vagrant, enables the account with the administrator inventory, runs
    the command, then disables the account again."""

    def __init__(self, instance, provider, provisioner):
        self.instance = instance
        self.provider = provider
        self.provisioner = provisioner

    def disabled(self):
        return bool(getattr(self.instance, 'vagrant_disabled', False))

    def _enable(self):
        Log.warning('the vagrant account is disabled on the lab: enabling it for the vagrant command')
        if not self.provider.boot_vms():
            Log.error('starting the lab VMs to enable the vagrant account failed')
            return False
        if not self.provisioner.run_disable_vagrant(disable_vagrant=False):
            Log.error('enabling the vagrant account failed: vagrant cannot log in to the lab VMs')
            return False
        self.instance.set_vagrant_disabled(False)
        return True

    def _disable(self):
        Log.info('disabling the vagrant account again')
        if not self.provisioner.run_disable_vagrant(disable_vagrant=True):
            Log.error('disabling the vagrant account again failed: it stays enabled, run disable_vagrant')
            return False
        self.instance.set_vagrant_disabled(True)
        return True

    def _host(self, vm):
        # VM "<lab>-SRV03" is inventory host srv03 (extension VMs may have no lab prefix)
        prefix = f'{self.instance.lab_name}-'
        return (vm[len(prefix):] if vm.startswith(prefix) else vm).lower()

    def halt(self, vms):
        """Shut the VMs down from inside with the administrator inventory: no vagrant login, the
        account stays disabled. None when the provider cannot see which VMs run."""
        running = self.provider.running_vms()
        if running is None:
            return None
        targets = [vm for vm in vms if vm in running]
        if not targets:
            return True
        Log.info(f'vagrant account disabled: shutting down {", ".join(targets)} from the guest')
        if not self.provisioner.run_shutdown([self._host(vm) for vm in targets], list(self.instance.extensions)):
            Log.warning('guest shutdown failed on some hosts: they are forced off after the wait')
        return self.provider.wait_halted(targets)

    def run(self, command, redisable=True):
        """command() -> bool. redisable=False when the command leaves the VMs off (halt): the
        account cannot be disabled again, it stays enabled."""
        if not self.disabled():
            return command()
        if not self._enable():
            return False
        result = command()
        if redisable:
            # even after a failed command: the account was disabled before the gate
            self._disable()
        else:
            Log.warning('the vagrant account stays enabled (VMs are off): run disable_vagrant after the next start')
        return result
