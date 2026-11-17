from goad.log import Log
from goad.scenario_resolver import ScenarioRefused


class ScenarioService:

    def __init__(self, instance, lab, provisioner):
        self.instance = instance
        self.lab = lab
        self.provisioner = provisioner

    def _run(self, scenario_name, target, install):
        scenario = self.lab.get_scenario(scenario_name)
        if scenario is None:
            Log.error(f'unknown scenario {scenario_name}')
            return False
        return bool(self.provisioner.run_scenario(scenario, target, self.instance.extensions, install=install))

    def enable(self, name, host):
        resolver = self.lab.get_scenario_resolver()
        try:
            target = resolver.check_enable(name, host, self.instance.scenarios)
        except ScenarioRefused as refused:
            for reason in refused.reasons:
                Log.error(reason)
            return False
        if self._run(name, target, True):
            self.instance.add_scenario(name, target)
            return True
        Log.error(f'scenario {name} failed on {target}, cleaning up')
        self._run(name, target, False)
        return False

    def _disable_entry(self, entry):
        if self._run(entry.name, entry.target, False):
            self.instance.remove_scenario(entry.name, entry.target)
            return True
        self.instance.mark_scenario_dirty(entry.name, entry.target)
        Log.error(f'uninstall of {entry.key} failed, marked dirty')
        return False

    def disable(self, name, host, cascade=False):
        resolver = self.lab.get_scenario_resolver()
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
        dependents = resolver.dependents(name, self.instance.scenarios)
        if dependents and not cascade:
            keys = ', '.join(d.key for d in dependents)
            Log.error(f'{name} has enabled dependents: {keys}; use --cascade')
            return False
        for victim in dependents + [entry]:
            if not self._disable_entry(victim):
                return False
        return True

    def _ordered_names(self):
        resolver = self.lab.get_scenario_resolver()
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
                if not self._run(entry.name, entry.target, True):
                    Log.error(f'reapply of {entry.key} failed')
                    return False
        return True

    def listing(self, show_all):
        resolver = self.lab.get_scenario_resolver()
        enabled = list(self.instance.scenarios)
        rows = [(e.name, 'dirty' if e.status == 'dirty' else 'enabled', e.target) for e in enabled]
        enabled_names = {e.name for e in enabled}
        for scenario, reasons in resolver.available(enabled):
            if scenario.name in enabled_names:
                continue
            if not reasons:
                rows.append((scenario.name, 'available', ''))
            elif show_all:
                rows.append((scenario.name, 'unavailable', '; '.join(reasons)))
        return rows
