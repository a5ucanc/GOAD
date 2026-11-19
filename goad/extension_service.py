from goad.log import Log

RESIDUE_WARNING = 'agents and domain objects the extension pushed to the lab stay (computer accounts, DNS records, agents)'


class ExtensionService:
    """install_extension / remove_extension with optional whole-lab snapshots."""

    def __init__(self, instance, provider, provision, snapshots=None, ask=None, scenarios=None, lab=None):
        self.instance = instance
        self.provider = provider
        # provision(name, install=True) -> bool runs the extension install or uninstall playbook
        self.provision = provision
        self.snapshots = snapshots
        self.ask = ask
        # scenario service of the instance: finds and disables the scenarios that need the extension
        self.scenarios = scenarios
        # lab of the instance: tells whether the extension has an uninstall playbook
        self.lab = lab

    def _prompts(self):
        return self.snapshots is not None and self.ask is not None and self.snapshots.supported()

    def install(self, name):
        if self._prompts() and self.ask(f'Take a lab snapshot before installing extension {name}? (y/N)'):
            if self.snapshots.take('ext', name, f'extension:{name}') is None:
                Log.error(f'extension {name} not installed: the lab snapshot failed')
                return False
        self.instance.enable_extension(name)
        # an extension without VMs installs onto the lab hosts: no vagrant up
        has_vms = bool(self.provider.extension_vm_names(name, self.instance.lab_name, self.instance.ip_range))
        if has_vms and not self.provider.install():
            Log.error(f'starting the VMs of extension {name} failed')
            return False
        return bool(self.provision(name))

    def _offer_revert(self, name):
        if not self._prompts():
            return None
        record = self.snapshots.find(f'extension:{name}')
        if record is None:
            return None
        reason = self.snapshots.revertable(record)
        if reason is not None:
            Log.warning(f'no revert offered: {reason}')
            return None
        for line in self.snapshots.report(record).lines():
            Log.info(line)
        if not self.ask(f'Revert the lab to {record.name} instead of removing? (y/N)'):
            return None
        return self.snapshots.revert(record)

    def _has_uninstall(self, name):
        if self.lab is None:
            return False
        extension = self.lab.get_extension(name)
        return extension is not None and extension.has_uninstall()

    def remove(self, name, yes=False):
        if name not in self.instance.extensions:
            Log.error(f'extension {name} is not installed')
            return False
        reverted = self._offer_revert(name)
        if reverted is not None:
            return reverted
        affected = self.scenarios.affected_by_extension_removal(name) if self.scenarios is not None else []
        keys = ', '.join(e.key for e in affected)
        if affected:
            Log.warning(f'extension {name} removal disables scenarios: {keys}')
        Log.warning(RESIDUE_WARNING)
        if not yes:
            if self.ask is None:
                if affected:
                    Log.error(f'remove_extension {name} disables scenarios or destroys VMs: use --yes')
                else:
                    Log.error(f'remove_extension {name} destroys VMs: use --yes')
                return False
            if affected:
                question = f'Remove extension {name} and disable scenarios {keys}? (y/N)'
            else:
                question = f'Remove extension {name} without revert? (y/N)'
            if not self.ask(question):
                return False
        if self.scenarios is not None and not self.scenarios.disable_entries(affected):
            Log.error(f'extension {name} kept: disabling scenarios failed')
            return False
        if self._has_uninstall(name) and not self.provision(name, install=False):
            Log.error(f'extension {name} kept: uninstall failed')
            return False
        vms = self.provider.extension_vm_names(name, self.instance.lab_name, self.instance.ip_range)
        # destroy while the generated Vagrantfile still defines the VMs
        if vms and not self.provider.destroy_vms(vms):
            Log.error(f'destroying the VMs of extension {name} failed, extension kept')
            return False
        self.instance.disable_extension(name)
        if self.snapshots is not None:
            self.snapshots.forget(f'extension:{name}')
        Log.success(f'extension {name} removed')
        return True
