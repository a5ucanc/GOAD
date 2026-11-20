import json

import pytest

from goad import GoadError
from goad.cli import NeedsConfirmation
from goad.templates.store import Template, TemplateStore


def _make(root, name, os_name, version):
    folder = root / name
    folder.mkdir(parents=True)
    Template(name=name, os=os_name, version=version, vmx=rf'C:\goad\templates\{name}\{name}.vmx',
             built_at='2026-11-20T10:00:00Z', packer_sha='abc').write(folder)


@pytest.fixture
def store(tmp_path, settings, vmrun):
    root = tmp_path / 'templates'
    root.mkdir()
    return TemplateStore(settings, vmrun, root=root)


def test_list_ignores_build_dir_and_foreign_folders(store):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    (store.root / '.build' / 'win2025-v2').mkdir(parents=True)
    (store.root / 'random').mkdir()
    (store.root / 'win2022-v1').mkdir()  # no template.json: unfinished
    assert [t.name for t in store.list()] == ['win2025-v1']


def test_next_version_counts_aborted_build(store):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    (store.root / '.build' / 'win2025-v2').mkdir(parents=True)
    assert store.next_version('win2025') == 3
    assert store.next_version('win2022') == 1


def test_latest(store):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    _make(store.root, 'win2025-v2', 'win2025', 2)
    assert store.latest('win2025').name == 'win2025-v2'
    assert store.latest('win11') is None


def test_windows_paths(store):
    assert store.windows_dir('win2025-v1') == r'C:\goad\templates\win2025-v1'
    assert store.windows_vmx('win2025-v1') == r'C:\goad\templates\win2025-v1\win2025-v1.vmx'


def test_delete_in_use_refused(store, settings):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    settings.state_dir.mkdir(parents=True)
    (settings.state_dir / 'lab.json').write_text(json.dumps({'templates': ['win2025-v1']}))
    with pytest.raises(GoadError, match='used by the deployed lab'):
        store.delete('win2025-v1', yes=True)
    assert (store.root / 'win2025-v1').is_dir()


def test_delete_unknown_refused(store):
    with pytest.raises(GoadError, match='no template'):
        store.delete('win2025-v9', yes=True)


def test_delete_non_tty_needs_yes(store, monkeypatch):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    with pytest.raises(NeedsConfirmation):
        store.delete('win2025-v1', yes=False)


def test_delete_removes_vm_and_folder(store, fake):
    _make(store.root, 'win2025-v1', 'win2025', 1)
    store.delete('win2025-v1', yes=True)
    assert fake.calls[-1][3:] == ['deleteVM', r'C:\goad\templates\win2025-v1\win2025-v1.vmx']
    assert not (store.root / 'win2025-v1').exists()
