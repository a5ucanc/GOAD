from goad.utils import READY


def provision_base_lab(instance, lab, provisioner, service, from_task=None):
    """Provision a base lab: vagrant is disabled afterwards, then scenarios are reapplied."""
    if instance.status == READY:
        # lab was provisioned before, so vagrant is disabled: re-enable it first
        if not provisioner.run_disable_vagrant(False):
            return False
    if from_task:
        ok = provisioner.run_from(from_task)
    else:
        ok = provisioner.run()
    if not ok:
        return False
    if not provisioner.run_disable_vagrant(True):
        return False
    return service.reapply()
