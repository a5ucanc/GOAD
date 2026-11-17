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
def test_scenario_playbooks_syntax(name, tmp_path):
    run_inv = tmp_path / "scenario_run_inventory"
    run_inv.write_text("[scenario_target]\ndc01\n\n[all:vars]\nscenario_name=%s\nscenario_target=dc01\n" % name)
    for pb in ["install.yml", "uninstall.yml"]:
        r = subprocess.run(
            [ANSIBLE_PLAYBOOK, "--syntax-check", "-i", "ad/GOAD-Mini-Base/data/inventory",
             "-i", str(run_inv),
             "scenarios/%s/ansible/%s" % (name, pb)],
            capture_output=True, cwd=str(ROOT))
        assert r.returncode == 0, r.stderr.decode()


def _role_includes(path):
    import yaml

    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.split(".")[-1] in ("include_role", "import_role") and isinstance(value, dict):
                    found.append(value["name"])
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(yaml.safe_load(path.read_text()))
    return found


ROLE_FILES = sorted(
    list((ROOT / "scenarios").glob("*/ansible/*.yml"))
    + list((ROOT / "ansible/roles/base_setting/tasks").glob("*.yml"))
)


@pytest.mark.parametrize("path", ROLE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_included_roles_resolve(path):
    role_path = ROOT / "ansible/roles/base_setting"
    for name in _role_includes(path):
        resolved = name.replace("{{ playbook_dir }}", str(path.parent)).replace("{{ role_path }}", str(role_path))
        assert "{{" not in resolved, name
        if "/" in name and ("{{ playbook_dir }}" in name or "{{ role_path }}" in name):
            target = Path(resolved)
        else:
            # a bare name is only found when the playbook runs from ansible/
            assert path.parent == ROOT / "ansible", "bare role name %s outside ansible/" % name
            target = ROOT / "ansible/roles" / name
        assert target.is_dir(), "%s: role %s not found at %s" % (path, name, target)
