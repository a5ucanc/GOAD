import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

DEFAULTS = {"description": "d", "type": "object", "requires": [], "target": "",
            "depends": [], "conflicts": [], "touches": [], "labs": ["*"]}


@pytest.fixture
def scenario_dir(tmp_path):
    def make(name, **fields):
        folder = tmp_path / name
        folder.mkdir(parents=True, exist_ok=True)
        data = dict(DEFAULTS)
        data.update(fields)
        path = folder / 'scenario.json'
        path.write_text(json.dumps(data))
        return str(path)
    return SimpleNamespace(make=make)
