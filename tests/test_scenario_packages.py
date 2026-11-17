import os
import shutil
import subprocess
from pathlib import Path

import pytest

from goad.scenario import Scenario

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = sorted(p.name for p in (ROOT / "scenarios").iterdir() if (p / "scenario.json").exists())
ANSIBLE_PLAYBOOK = os.path.expanduser("~/.goad/.venv/bin/ansible-playbook")
if not os.path.exists(ANSIBLE_PLAYBOOK):
    ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_package_complete(name):
    base = ROOT / "scenarios" / name
    Scenario.from_file(name, str(base / "scenario.json"))
    for f in ["ansible/install.yml", "ansible/uninstall.yml", "README.md"]:
        assert (base / f).exists(), f


@pytest.mark.parametrize("name", SCENARIOS)
def test_setting_scenario_touches_known_keys(name):
    s = Scenario.from_file(name, str(ROOT / "scenarios" / name / "scenario.json"))
    if s.type == "setting":
        tasks = ROOT / "ansible/roles/base_setting/tasks"
        known = {p.stem.replace("_", ".", 1) for p in tasks.glob("*.yml") if p.stem != "main"}
        assert s.touches and set(s.touches) <= known


@pytest.mark.skipif(ANSIBLE_PLAYBOOK is None, reason="ansible-playbook not found")
@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_playbooks_syntax(name):
    for pb in ["install.yml", "uninstall.yml"]:
        r = subprocess.run(
            [ANSIBLE_PLAYBOOK, "--syntax-check", "-i", "ad/GOAD-Mini-Base/data/inventory",
             "-e", "scenario_target=dc01 scenario_name=%s" % name,
             "scenarios/%s/ansible/%s" % (name, pb)],
            capture_output=True, cwd=str(ROOT))
        assert r.returncode == 0, r.stderr.decode()
