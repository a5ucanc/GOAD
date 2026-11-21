"""Run by hand on the VMware host with a win2025 template and no lab deployed: pytest -m live -k lab -s."""
import pytest

from goad.cli import main
from goad.host.runner import Runner
from goad.settings import load_settings
from goad.state import load_state
from goad.templates.store import TemplateStore
from goad.vmware.vmrun import Vmrun

pytestmark = pytest.mark.live


def test_lab_lifecycle():
    settings, runner = load_settings(), Runner()
    if TemplateStore(settings, Vmrun(runner, settings)).latest('win2025') is None:
        pytest.skip('no win2025 template built')
    if load_state(settings) is not None:
        pytest.fail('a lab is already deployed: run goad lab destroy first')
    try:
        assert main(['lab', 'deploy', '1domain']) == 0
        assert main(['snapshot', 'take', 'live-check']) == 0
        assert main(['lab', 'reset', 'live-check']) == 0
        assert main(['lab', 'reset']) == 0
    except BaseException:
        main(['lab', 'destroy', '--yes'])   # best effort: the original failure is the one reported
        raise
    assert main(['lab', 'destroy', '--yes']) == 0
