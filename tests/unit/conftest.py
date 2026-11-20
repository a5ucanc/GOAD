import pytest

from goad.host.runner import FakeRunner
from goad.settings import Settings
from goad.vmware.vmrun import Vmrun


@pytest.fixture
def fake():
    return FakeRunner()


@pytest.fixture
def settings(tmp_path):
    return Settings(state_dir=tmp_path / 'state')


@pytest.fixture
def vmrun(fake, settings):
    return Vmrun(fake, settings)
