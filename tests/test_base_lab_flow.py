from types import SimpleNamespace

import pytest

from goad.base_lab_flow import provision_base_lab
from goad.utils import PROVIDED, READY


class Fakes:
    def __init__(self):
        self.log = []
        self.fail = None
        self.instance = SimpleNamespace(status="created", vagrant_disabled=False)
        self.instance.set_vagrant_disabled = self._set_vagrant_disabled
        self.lab = SimpleNamespace()
        fakes = self

        class Provisioner:
            def _step(self, name, label=None):
                fakes.log.append(label or name)
                return fakes.fail != name

            def run(self):
                return self._step("run")

            def run_from(self, task):
                return self._step("run", "run_from:" + task)

            def run_disable_vagrant(self, disable_vagrant):
                return self._step("disable_vagrant" if disable_vagrant else "enable_vagrant")

        class Service:
            def reapply(self):
                return fakes._reapply()

        self.provisioner = Provisioner()
        self.service = Service()

    def _set_vagrant_disabled(self, value):
        self.log.append("flag=%s" % value)
        self.instance.vagrant_disabled = value

    def _reapply(self):
        self.log.append("reapply")
        return self.fail != "reapply"

    def args(self):
        return (self.instance, self.lab, self.provisioner, self.service)


@pytest.fixture
def fakes():
    return Fakes()


def test_first_provision_skips_enable_vagrant(fakes):
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["run", "disable_vagrant", "flag=True", "reapply"]
    assert fakes.instance.vagrant_disabled


def test_reprovision_enables_vagrant_first(fakes):
    fakes.instance.status = READY
    fakes.instance.vagrant_disabled = True
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "flag=False", "run", "disable_vagrant", "flag=True", "reapply"]


def test_reinstall_with_status_provided_and_vagrant_disabled_enables_vagrant_first(fakes):
    # a new install on a READY instance resets the status to PROVIDED before provisioning
    fakes.instance.status = PROVIDED
    fakes.instance.vagrant_disabled = True
    assert provision_base_lab(*fakes.args())
    assert fakes.log[:2] == ["enable_vagrant", "flag=False"]


def test_ready_status_without_flag_skips_enable_vagrant(fakes):
    fakes.instance.status = READY
    assert provision_base_lab(*fakes.args())
    assert fakes.log[0] == "run"


def test_run_from_used_when_task_given(fakes):
    fakes.instance.vagrant_disabled = True
    provision_base_lab(*fakes.args(), from_task="ad-data.yml")
    assert fakes.log[2] == "run_from:ad-data.yml"


def test_failed_run_leaves_vagrant_enabled(fakes):
    fakes.instance.vagrant_disabled = True
    fakes.fail = "run"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "flag=False", "run"]
    assert not fakes.instance.vagrant_disabled


def test_failed_enable_aborts_and_keeps_flag(fakes):
    fakes.instance.vagrant_disabled = True
    fakes.fail = "enable_vagrant"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant"]
    assert fakes.instance.vagrant_disabled


def test_failed_disable_aborts_before_reapply(fakes):
    fakes.fail = "disable_vagrant"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["run", "disable_vagrant"]
    assert not fakes.instance.vagrant_disabled


def test_reapply_result_returned(fakes):
    fakes.fail = "reapply"
    assert not provision_base_lab(*fakes.args())
