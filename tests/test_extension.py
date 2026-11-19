import json

import pytest

from goad.extension import Extension
from goad.goadpath import GoadPath


@pytest.fixture
def ext_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(GoadPath, 'get_extensions_path', staticmethod(lambda: str(tmp_path)))

    def make(name, info=None, providers=False, uninstall=False):
        folder = tmp_path / name
        (folder / 'ansible').mkdir(parents=True)
        if info is not None:
            (folder / 'extension.json').write_text(json.dumps(info))
        if providers:
            (folder / 'providers' / 'vmware').mkdir(parents=True)
        if uninstall:
            (folder / 'ansible' / 'uninstall.yml').write_text('---\n')
        return Extension(name)
    return make


INFO = {"name": "mssql", "description": "d", "machines": [], "compatibility": ["GOAD-Base"],
        "capabilities": {"GOAD-Base": {"mssql": ["srv02", "srv03"]}}}


def test_capabilities_for_lab(ext_dir):
    ext = ext_dir('mssql', INFO)
    assert ext.capabilities_for('GOAD-Base') == {"mssql": ["srv02", "srv03"]}


def test_capabilities_for_returns_a_copy(ext_dir):
    ext = ext_dir('mssql', INFO)
    ext.capabilities_for('GOAD-Base')['mssql'].append('x')
    assert ext.capabilities_for('GOAD-Base') == {"mssql": ["srv02", "srv03"]}


def test_capabilities_for_other_lab_is_empty(ext_dir):
    assert ext_dir('mssql', INFO).capabilities_for('GOAD') == {}


def test_no_capabilities_key(ext_dir):
    info = {k: v for k, v in INFO.items() if k != 'capabilities'}
    assert ext_dir('mssql', info).capabilities_for('GOAD-Base') == {}


@pytest.mark.parametrize("caps", [[], "x", {"GOAD-Base": []}, {"GOAD-Base": {"mssql": "srv02"}}])
def test_malformed_capabilities_ignored(ext_dir, caps):
    info = dict(INFO, capabilities=caps)
    assert ext_dir('mssql', info).capabilities_for('GOAD-Base') == {}


def test_no_extension_json(ext_dir):
    assert ext_dir('mssql').capabilities_for('GOAD-Base') == {}


def test_no_providers_folder(ext_dir):
    assert ext_dir('mssql', INFO).list_providers_name() == []


def test_providers_folder_listed(ext_dir):
    assert ext_dir('mssql', INFO, providers=True).list_providers_name() == ['vmware']
