def provision_base_lab(instance, lab, provisioner, service, from_task=None):
    """Provision a base lab: vagrant is disabled afterwards, then scenarios are reapplied."""
    if instance.vagrant_disabled:
        # vagrant was disabled by a previous run: re-enable it first
        if not provisioner.run_disable_vagrant(False):
            return False
        instance.set_vagrant_disabled(False)
    if from_task:
        ok = provisioner.run_from(from_task)
    else:
        ok = provisioner.run()
    if not ok:
        return False
    if not provisioner.run_disable_vagrant(True):
        return False
    instance.set_vagrant_disabled(True)
    return service.reapply()
