from goad.log import Log
from goad.scenario_resolver import ScenarioRefused


class ScenarioService:

    def __init__(self, instance, lab, provisioner, snapshots=None, ask=None, snapshot_prompts=True):
        self.instance = instance
        self.lab = lab
        self.provisioner = provisioner
        # snapshots: LabSnapshots; ask(prompt) -> bool. Without both, nothing is ever asked.
        self.snapshots = snapshots
        self.ask = ask
        # False (--no-snapshot): never ask to take or revert to a snapshot
        self.snapshot_prompts = snapshot_prompts

    def _prompts(self):
        return (self.snapshot_prompts and self.snapshots is not None and self.ask is not None
                and self.snapshots.supported())

    def _forget(self, key):
        if self.snapshots is not None:
            self.snapshots.forget(key)

    def _run(self, scenario_name, target, install):
        scenario = self.lab.get_scenario(scenario_name)
        if scenario is None:
            Log.error(f'unknown scenario {scenario_name}')
            return False
        return bool(self.provisioner.run_scenario(scenario, target, self.instance.extensions, install=install))

    def enable(self, name, host):
        resolver = self.lab.get_scenario_resolver(self.instance.extensions)
        try:
            target = resolver.check_enable(name, host, self.instance.scenarios)
        except ScenarioRefused as refused:
            for reason in refused.reasons:
                Log.error(reason)
            return False
        key = f'{name}@{target}'
        if self._prompts() and self.ask(f'Take a lab snapshot before enabling {key}? (y/N)'):
            if self.snapshots.take('scn', key, key) is None:
                Log.error(f'{name} not enabled: the lab snapshot failed')
                return False
        if self._run(name, target, True):
            self.instance.add_scenario(name, target)
            return True
        Log.error(f'scenario {name} failed on {target}, cleaning up')
        if self._run(name, target, False):
            self._forget(key)
        else:
            # keep the residue visible: a dirty entry can be retried with disable_scenario
            self.instance.add_scenario(name, target)
            self.instance.mark_scenario_dirty(name, target)
            Log.error(f'cleanup of {name}@{target} failed, marked dirty: run disable_scenario {name} {target}')
        return False

    def _disable_entry(self, entry):
        if self._run(entry.name, entry.target, False):
            self.instance.remove_scenario(entry.name, entry.target)
            self._forget(entry.key)
            return True
        self.instance.mark_scenario_dirty(entry.name, entry.target)
        Log.error(f'uninstall of {entry.key} failed, marked dirty')
        return False

    def disable(self, name, host, cascade=False):
        resolver = self.lab.get_scenario_resolver(self.instance.extensions)
        entries = [e for e in self.instance.scenarios if e.name == name]
        if host is not None:
            entries = [e for e in entries if e.target == host]
        if not entries:
            Log.error(f'{name} is not enabled' + (f' on {host}' if host else ''))
            return False
        if len(entries) > 1:
            targets = ', '.join(e.target for e in entries)
            Log.error(f'{name} is enabled on {targets}: name the host')
            return False
        entry = entries[0]
        reverted = self._offer_revert(entry)
        if reverted is not None:
            return reverted
        dependents = resolver.dependents(name, self.instance.scenarios, entry.target)
        if dependents and not cascade:
            keys = ', '.join(d.key for d in dependents)
            Log.error(f'{name} has enabled dependents: {keys}; use --cascade')
            return False
        for victim in dependents + [entry]:
            if not self._disable_entry(victim):
                return False
        return True

    def affected_by_extension_removal(self, extension):
        """Enabled scenarios that lose a capability once extension is removed, plus their dependents.

        Ordered for uninstall: dependents first.
        """
        remaining = [e for e in self.instance.extensions if e != extension]
        capabilities = self.lab.effective_capabilities(remaining) or {}
        resolver = self.lab.get_scenario_resolver(self.instance.extensions)
        affected = []
        for entry in self.instance.scenarios:
            scenario = resolver.scenarios.get(entry.name)
            if scenario is None:
                continue
            missing = any(cap not in capabilities for cap in scenario.requires)
            if scenario.target and entry.target not in (capabilities.get(scenario.target) or []):
                missing = True
            if missing:
                affected.append(entry)
        for entry in list(affected):
            for dependent in resolver.dependents(entry.name, self.instance.scenarios, entry.target):
                if dependent not in affected:
                    affected.append(dependent)
        rank = {name: i for i, name in enumerate(resolver.install_order(list(dict.fromkeys(e.name for e in affected))))}
        return sorted(affected, key=lambda e: -rank[e.name])

    def disable_entries(self, entries):
        """Uninstall entries in the given order, without revert prompts; stop at the first failure."""
        for entry in entries:
            if not self._disable_entry(entry):
                return False
        return True

    def _offer_revert(self, entry):
        """Revert result when the user chose the revert, None to go on with the uninstall."""
        if not self._prompts():
            return None
        record = self.snapshots.find(entry.key)
        if record is None:
            return None
        reason = self.snapshots.revertable(record)
        if reason is not None:
            Log.warning(f'no revert offered: {reason}')
            return None
        for line in self.snapshots.report(record).lines():
            Log.info(line)
        if not self.ask(f'Revert the lab to {record.name} instead of disabling? (y/N)'):
            return None
        return self.snapshots.revert(record)

    def _snapshot_name(self, key):
        record = self.snapshots.find(key) if self.snapshots is not None else None
        return record.name if record is not None else ''

    def _ordered_names(self):
        resolver = self.lab.get_scenario_resolver(self.instance.extensions)
        names = []
        for entry in self.instance.scenarios:
            if entry.name not in names:
                names.append(entry.name)
        return resolver.install_order(names)

    def reset(self):
        for name in reversed(self._ordered_names()):
            for entry in [e for e in self.instance.scenarios if e.name == name]:
                if not self._disable_entry(entry):
                    return False
        return True

    def reapply(self):
        for name in self._ordered_names():
            for entry in [e for e in self.instance.scenarios if e.name == name]:
                if entry.status == 'dirty':
                    # never re-install residue the user tried to remove
                    Log.warning(f'{entry.key} is dirty, not reapplied: run disable_scenario {entry.name} {entry.target}')
                    continue
                if not self._run(entry.name, entry.target, True):
                    Log.error(f'reapply of {entry.key} failed')
                    return False
        return True

    def listing(self, show_all):
        resolver = self.lab.get_scenario_resolver(self.instance.extensions)
        enabled = list(self.instance.scenarios)
        rows = [(e.name, 'dirty' if e.status == 'dirty' else 'enabled', e.target, self._snapshot_name(e.key)) for e in enabled]
        enabled_names = {e.name for e in enabled}
        for scenario, reasons in resolver.available(enabled):
            if scenario.name in enabled_names:
                continue
            if not reasons:
                rows.append((scenario.name, 'available', '', ''))
            elif show_all:
                rows.append((scenario.name, 'unavailable', '; '.join(reasons), ''))
        return rows
