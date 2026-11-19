def provision_base_lab(instance, lab, provisioner, service, from_task=None, provision_extension=None):
    """Provision a base lab: vagrant is disabled afterwards, the installed extensions are provisioned
    (scenarios may need the services they install), then scenarios are reapplied."""
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
    if provision_extension is not None:
        for extension_name in list(getattr(instance, 'extensions', [])):
            if not provision_extension(extension_name):
                return False
    return service.reapply()
