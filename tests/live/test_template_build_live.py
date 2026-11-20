"""Run by hand on the VMware host: pytest -m live -k build (builds a real template: an hour or more)."""
import pytest

from goad.host.runner import Runner
from goad.settings import load_settings
from goad.templates.build import build_template
from goad.templates.store import TemplateStore
from goad.vmware.vmrun import Vmrun

pytestmark = pytest.mark.live


@pytest.mark.parametrize('os_name', ['win2025'])
def test_build_creates_template_with_base_snapshot(os_name):
    settings, runner = load_settings(), Runner()
    vmrun = Vmrun(runner, settings)
    store = TemplateStore(settings, vmrun)
    template = build_template(os_name, settings, runner, store)
    assert template.name in [t.name for t in store.list()]
    assert 'base' in vmrun.snapshots(template.vmx)
