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


@pytest.fixture
def deployed(settings):
    from goad.lab.context import vm_path
    from goad.lab.definition import load_lab, shipped_lab
    from goad.state import (HostState, LabState, SnapshotRecord, save_state, working_lab_path)
    text = shipped_lab('2domains').read_text()
    path = working_lab_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    lab = load_lab(path)
    hosts = {name: HostState(vmx=vm_path(settings, name), template=f'{h.os}-v1', hostname=h.hostname,
                             ip=lab.ip(name, '192.168.56'), ready=True)
             for name, h in lab.hosts.items()}
    state = LabState(lab='2domains', ip_range='192.168.56', step='finish', hosts=hosts,
                     templates=sorted({h.template for h in hosts.values()}), current='base',
                     snapshots=[SnapshotRecord(name='base', taken_at='2026-11-21T00:00:00Z', label='', lab_yml=text)])
    save_state(settings, state)
    return state
