"""Run by hand on the VMware host after building templates: pytest -m live -k smoke."""
import pytest

from goad.host.runner import Runner
from goad.settings import OS_NAMES, load_settings
from goad.templates.smoke import smoke_test
from goad.templates.store import TemplateStore
from goad.vmware.vmrun import Vmrun

pytestmark = pytest.mark.live


@pytest.mark.parametrize('os_name', OS_NAMES)
def test_smoke(os_name):
    settings, runner = load_settings(), Runner()
    store = TemplateStore(settings, Vmrun(runner, settings))
    if store.latest(os_name) is None:
        pytest.skip(f'no {os_name} template built')
    assert smoke_test(os_name, settings, runner, store) > 0
