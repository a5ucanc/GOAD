from types import SimpleNamespace

import pytest

from goad.base_lab_flow import provision_base_lab
from goad.utils import READY


class Fakes:
    def __init__(self):
        self.log = []
        self.fail = None
        self.instance = SimpleNamespace(status="created")
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

    def _reapply(self):
        self.log.append("reapply")
        return self.fail != "reapply"

    def args(self):
        return (self.instance, self.lab, self.provisioner, self.service)


@pytest.fixture
def fakes():
    return Fakes()


def test_first_provision_skips_enable_vagrant(fakes):
    fakes.instance.status = "created"
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["run", "disable_vagrant", "reapply"]


def test_reprovision_enables_vagrant_first(fakes):
    fakes.instance.status = READY
    assert provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "run", "disable_vagrant", "reapply"]


def test_run_from_used_when_task_given(fakes):
    fakes.instance.status = READY
    provision_base_lab(*fakes.args(), from_task="ad-data.yml")
    assert fakes.log[1] == "run_from:ad-data.yml"


def test_failed_run_leaves_vagrant_enabled(fakes):
    fakes.instance.status = READY
    fakes.fail = "run"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant", "run"]


def test_failed_enable_aborts(fakes):
    fakes.instance.status = READY
    fakes.fail = "enable_vagrant"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["enable_vagrant"]


def test_failed_disable_aborts_before_reapply(fakes):
    fakes.fail = "disable_vagrant"
    assert not provision_base_lab(*fakes.args())
    assert fakes.log == ["run", "disable_vagrant"]


def test_reapply_result_returned(fakes):
    fakes.fail = "reapply"
    assert not provision_base_lab(*fakes.args())
