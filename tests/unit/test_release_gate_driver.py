"""The live release gate driver, run against a fake goad CLI: order, counts and failure handling."""
import contextlib

import pytest

import tests.live.test_release_gate as gate
from goad.settings import Settings
from goad.state import HostState, LabState, SnapshotRecord, delete_state, load_state, save_state, working_lab_path


@pytest.fixture
def fake_gate(tmp_path, monkeypatch):
    settings = Settings(state_dir=tmp_path / 'state')
    calls = []

    def main(argv):
        calls.append(argv[:2])
        if argv[:2] == ['lab', 'deploy']:
            working_lab_path(settings).parent.mkdir(parents=True, exist_ok=True)
            working_lab_path(settings).write_text('lab\n')
            save_state(settings, LabState('2domains', '192.168.56', 'finish',
                                          {'dc01': HostState('C:\\none\\dc01.vmx', 'win2025-v1', 'k', '192.168.56.10')},
                                          ['win2025-v1'], [SnapshotRecord('base', 't', '', 'lab\n')], 'base'))
        elif argv[:2] == ['lab', 'reset']:
            working_lab_path(settings).write_text('lab\n')
        elif argv[:2] == ['lab', 'destroy']:
            delete_state(settings)
        return 0

    monkeypatch.setattr(gate, 'load_settings', lambda: settings)
    monkeypatch.setattr(gate, 'main', main)
    monkeypatch.setattr(gate, 'keep_host_awake', contextlib.nullcontext)
    monkeypatch.setattr(gate, 'wait_healthy', lambda s, r: 0.0)
    monkeypatch.setattr(gate, 'add_marker', lambda ip, name: None)
    monkeypatch.setattr(gate, 'marker_exists', lambda ip, name: False)
    # VM folders of the fake lab live under tmp_path, never under the host's real lab_root.
    monkeypatch.setattr(gate, 'vm_folder', lambda s, host: str(tmp_path / 'vms' / host))
    monkeypatch.setattr(gate, 'to_wsl', lambda path: __import__('pathlib').Path(path))
    return settings, calls, monkeypatch


def report_text(settings):
    return next((settings.state_dir / 'logs').glob('release-gate-*.md')).read_text()


def test_gate_runs_every_step_in_order(fake_gate):
    settings, calls, _ = fake_gate
    gate.test_release_gate()
    assert calls.count(['template', 'test']) == 4
    assert calls.count(['lab', 'deploy']) == 3 and calls.count(['snapshot', 'take']) == 3
    assert calls.count(['lab', 'reset']) == 5 and calls.count(['lab', 'destroy']) == 3
    assert calls.index(['lab', 'reset']) < calls.index(['lab', 'destroy'])
    assert 'Result: PASS' in report_text(settings)
    assert load_state(settings) is None


def test_marker_left_after_reset_fails_the_gate_and_destroys_the_lab(fake_gate):
    settings, calls, monkeypatch = fake_gate
    monkeypatch.setattr(gate, 'marker_exists', lambda ip, name: True)
    with pytest.raises(AssertionError):
        gate.test_release_gate()
    text = report_text(settings)
    assert 'reset 0 s FAILED reset 1/5: gate-marker-1 still in AD after reset' in text
    assert 'Result: FAIL' in text
    assert calls.count(['lab', 'reset']) == 1 and calls[-1] == ['lab', 'destroy']
    assert load_state(settings) is None
