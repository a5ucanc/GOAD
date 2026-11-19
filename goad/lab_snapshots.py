from dataclasses import dataclass, field
from typing import Dict, List, Optional

from goad.lab_snapshot_record import SnapshotRecord
from goad.log import Log


def _key(scenario):
    return f"{scenario['name']}@{scenario['target']}"


@dataclass
class RevertReport:
    record: SnapshotRecord
    stack: List[SnapshotRecord]
    removed: str
    lost_scenarios: List[str] = field(default_factory=list)
    # every extension the record does not list (the removed one included) -> its VMs, destroyed
    lost_extensions: Dict[str, List[str]] = field(default_factory=dict)
    restored_scenarios: List[str] = field(default_factory=list)
    deleted_snapshots: List[str] = field(default_factory=list)
    vagrant_change: Optional[str] = None

    def lines(self):
        lines = ['lab snapshots (oldest first):']
        width = max(len(record.name) for record in self.stack)
        for record in self.stack:
            mark = ''
            if record.name == self.record.name:
                mark = '  <- revert point'
            elif record.name in self.deleted_snapshots:
                mark = '  deleted'
            lines.append(f'  {record.name:<{width}}  for {record.taken_for}{mark}')
        lines.append(f'revert to {self.record.name}:')
        lines.append(f'  removed:  {self.removed}')
        if self.lost_scenarios:
            lines.append(f'  lost:     {", ".join(self.lost_scenarios)}')
        if self.restored_scenarios:
            lines.append(f'  restored: {", ".join(self.restored_scenarios)}')
        for extension, vms in self.lost_extensions.items():
            lines.append(f'  extension {extension}: {", ".join(vms) or "no VM"} destroyed')
        if self.vagrant_change:
            lines.append(f'  {self.vagrant_change}')
        return lines


class LabSnapshots:
    """Named whole-lab snapshots and the instance state they captured."""

    def __init__(self, instance, provider, lab_name, ip_range, after_restore=None):
        self.instance = instance
        self.provider = provider
        self.lab_name = lab_name
        self.ip_range = ip_range
        # after_restore() -> bool: resync guest clocks (restored VMs resume with the snapshot's clock)
        self.after_restore = after_restore

    def supported(self):
        return bool(self.provider is not None and self.provider.supports_named_snapshots())

    def _vms_listing(self, name, listing=None):
        listing = self.provider.snapshot_list() if listing is None else listing
        return [vm for vm, names in listing.items() if name in names]

    def take(self, prefix, label, taken_for):
        name = self.instance.next_snapshot_name(prefix, label)
        Log.info(f'taking lab snapshot {name}')
        if not self.provider.snapshot_save(name):
            partial = self._vms_listing(name)
            if partial:
                self.provider.snapshot_delete(name, partial)
            Log.error(f'lab snapshot {name} failed')
            return None
        record = self.instance.capture_state(name, taken_for)
        self.instance.add_snapshot_record(record)
        return record

    def find(self, taken_for):
        return self.instance.find_snapshot_record(taken_for)

    def _later_extensions(self, record):
        return {extension: self.provider.extension_vm_names(extension, self.lab_name, self.ip_range)
                for extension in self.instance.extensions if extension not in record.extensions}

    def _covered_vms(self, record):
        later = {vm for vms in self._later_extensions(record).values() for vm in vms}
        return [vm for vm in self.provider.vm_names() if vm not in later]

    def revertable(self, record):
        # an extension removed without a revert would come back in instance.json without its VMs
        for extension in record.extensions:
            if extension not in self.instance.extensions:
                return f'extension {extension} in {record.name} is no longer installed'
        listing = self.provider.snapshot_list()
        for vm in self._covered_vms(record):
            if record.name not in listing.get(vm, []):
                return f'snapshot {record.name} missing on {vm}'
        return None

    def report(self, record):
        current = [scenario.key for scenario in self.instance.scenarios]
        captured = [_key(scenario) for scenario in record.scenarios]
        index = self.instance.snapshots.index(record)
        vagrant_change = None
        if record.vagrant_disabled != self.instance.vagrant_disabled:
            vagrant_change = 'vagrant account: ' + ('disabled again' if record.vagrant_disabled else 'enabled again')
        return RevertReport(
            record=record,
            stack=list(self.instance.snapshots),
            removed=record.taken_for,
            lost_scenarios=[key for key in current if key not in captured and key != record.taken_for],
            lost_extensions=self._later_extensions(record),
            restored_scenarios=[key for key in captured if key not in current],
            deleted_snapshots=[later.name for later in self.instance.snapshots[index + 1:]],
            vagrant_change=vagrant_change)

    def revert(self, record):
        later = self._later_extensions(record)
        existing = self.provider.vm_names()
        to_destroy = [vm for vms in later.values() for vm in vms if vm in existing]
        covered = self._covered_vms(record)
        if to_destroy and not self.provider.destroy_vms(to_destroy):
            Log.error('destroying the VMs of later extensions failed, revert stopped')
            return False
        # the destroyed extensions are gone whatever the restore does
        for extension in later:
            self.instance.disable_extension(extension)
        if not self.provider.snapshot_restore(record.name, covered):
            Log.error(f'lab partially reverted to {record.name}: run the same command again to finish '
                      f'(instance.json still lists the scenarios of the current state)')
            return False
        index = self.instance.snapshots.index(record)
        dropped = [r.name for r in self.instance.snapshots[index:]]
        self.instance.apply_state(record)
        # after apply_state: the inventories no longer list the destroyed extension hosts
        if self.after_restore is not None and not self.after_restore():
            Log.warning('clock sync after the revert failed: run sync_time.yml before attacking (Kerberos needs synced clocks)')
        listing = self.provider.snapshot_list()
        for name in dropped:
            vms = self._vms_listing(name, listing)
            if vms and not self.provider.snapshot_delete(name, vms):
                Log.warning(f'could not delete snapshot {name} on {", ".join(vms)}')
        self.instance.remove_snapshot_records(dropped)
        Log.success(f'lab reverted to {record.name}')
        return True

    def rows(self):
        """(snapshot, taken for, scenarios captured, extensions, VM presence) oldest first, then the
        scn-/ext- snapshots VMware holds without a goad record."""
        listing = self.provider.snapshot_list()
        rows = []
        for record in self.instance.snapshots:
            covered = self._covered_vms(record)
            missing = [vm for vm in covered if record.name not in listing.get(vm, [])]
            presence = f'missing on {", ".join(missing)}' if missing else f'{len(covered)}/{len(covered)}'
            rows.append((record.name, record.taken_for, ', '.join(_key(s) for s in record.scenarios),
                         ', '.join(record.extensions), presence))
        known = {record.name for record in self.instance.snapshots}
        orphans = []
        for names in listing.values():
            for name in names:
                if name.startswith(('scn-', 'ext-')) and name not in known and name not in orphans:
                    orphans.append(name)
        for name in orphans:
            holders = [vm for vm, names in listing.items() if name in names]
            rows.append((name, '(no record)', '', '', f'{len(holders)}/{len(listing)}'))
        return rows

    def forget(self, taken_for):
        record = self.find(taken_for)
        if record is None:
            return True
        vms = self._vms_listing(record.name)
        ok = True
        if vms and not self.provider.snapshot_delete(record.name, vms):
            Log.warning(f'could not delete snapshot {record.name} on {", ".join(vms)}')
            ok = False
        self.instance.remove_snapshot_records([record.name])
        return ok
