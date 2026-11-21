import pytest

from goad.state import (HostState, LabState, SnapshotRecord, delete_state, load_state,
                        save_state, state_path, templates_in_use, working_lab_path)


def test_round_trip(settings):
    state = LabState(lab='2domains', ip_range='192.168.56', step='clone',
                     hosts={'dc01': HostState(r'C:\goad\lab\dc01\dc01.vmx', 'win2025-v1', 'kingslanding', '192.168.56.10')},
                     templates=['win2025-v1'],
                     snapshots=[SnapshotRecord('base', '2026-11-21T10:00:00Z', '', 'name: 2domains\n')],
                     current='base', durations={'clone': 12.5})
    save_state(settings, state)
    assert load_state(settings) == state
    assert templates_in_use(settings) == {'win2025-v1'}


def test_missing_state_is_none(settings):
    assert load_state(settings) is None
    assert templates_in_use(settings) == set()


def test_save_is_atomic(settings, monkeypatch):
    save_state(settings, LabState(lab='1domain', ip_range='192.168.56'))

    def boom(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr('os.replace', boom)
    with pytest.raises(OSError):
        save_state(settings, LabState(lab='2domains', ip_range='192.168.56'))
    assert load_state(settings).lab == '1domain'   # old file intact


def test_delete_state_removes_working_files(settings):
    save_state(settings, LabState(lab='1domain', ip_range='192.168.56'))
    working_lab_path(settings).write_text('x')
    delete_state(settings)
    delete_state(settings)   # second call is a no-op
    assert not state_path(settings).exists() and not working_lab_path(settings).exists()


def test_deployed_and_snapshot_lookup():
    snap = SnapshotRecord('base', '2026-11-21T10:00:00Z', '', 'x')
    state = LabState(lab='1domain', ip_range='192.168.56', snapshots=[snap])
    assert not state.deployed
    state.step = 'finish'
    assert state.deployed
    assert state.snapshot('base') is snap
    assert state.snapshot('nope') is None
