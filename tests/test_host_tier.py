import itertools
import json
import os
import subprocess
import sys

import jinja2
import pytest
import yaml

TASK_FILE = "ansible/roles/base_setting/tasks/host_tier.yml"
TIER_GROUPS = {"T0-Admins", "T1-ServerAdmins", "T2-WorkstationAdmins"}
BASE_LABS = ["GOAD-Base", "GOAD-Light-Base", "GOAD-Mini-Base"]


def load_lab(lab):
    return json.load(open(f"ad/{lab}/data/config.json"))["lab"]


def render_tier(lab, tier):
    """Render the deny lists the way Ansible would, with the set_fact task of host_tier.yml."""
    tasks = yaml.safe_load(open(TASK_FILE))
    task = next(t for t in tasks if "ansible.builtin.set_fact" in t)
    env = jinja2.Environment()
    env.filters["product"] = lambda a, b: list(itertools.product(a, b))
    context = {"lab": load_lab(lab), "setting_value": tier, **task.get("vars", {})}

    def render(expr):
        # each fact is a single "{{ ... }}" expression returning a list
        return env.compile_expression(expr.strip()[2:-2].strip())(**context)

    facts = task["ansible.builtin.set_fact"]
    return render(facts["tier_deny_interactive"]), render(facts["tier_deny_network"])


@pytest.mark.parametrize("lab", BASE_LABS)
@pytest.mark.parametrize("tier", ["0", "1", "2"])
def test_deny_lists_only_name_tier_groups_of_lab_domains(lab, tier):
    inter, net = render_tier(lab, tier)
    nbs = {d["netbios_name"].upper() for d in load_lab(lab)["domains"].values()}
    for entry in inter + net:
        nb, group = entry.split("\\")
        assert nb.upper() in nbs
        assert group in TIER_GROUPS


def test_tier0_never_denies_network():
    assert render_tier("GOAD-Base", "0")[1] == []


def test_tier1_does_not_deny_t0_network():
    assert not any(e.endswith("\\T0-Admins") for e in render_tier("GOAD-Base", "1")[1])


def test_tier1_denies_t0_interactive():
    assert {e for e in render_tier("GOAD-Base", "1")[0] if e.endswith("T0-Admins")} == \
        {"SEVENKINGDOMS\\T0-Admins", "NORTH\\T0-Admins", "ESSOS\\T0-Admins"}


def test_tier0_denies_t1_interactive_for_every_domain():
    assert {e for e in render_tier("GOAD-Base", "0")[0] if e.endswith("T1-ServerAdmins")} == \
        {"SEVENKINGDOMS\\T1-ServerAdmins", "NORTH\\T1-ServerAdmins", "ESSOS\\T1-ServerAdmins"}


def test_tier2_denies_t0_and_t1_everywhere():
    inter, net = render_tier("GOAD-Mini-Base", "2")
    assert sorted(inter) == sorted(net) == ["SEVENKINGDOMS\\T0-Admins", "SEVENKINGDOMS\\T1-ServerAdmins"]


ANSIBLE_PLAYBOOK = os.path.join(os.path.dirname(sys.executable), "ansible-playbook")


@pytest.mark.skipif(not os.path.exists(ANSIBLE_PLAYBOOK), reason="ansible-playbook not installed")
def test_ansible_renders_single_backslash(tmp_path):
    # Ansible templates set_fact values differently from plain Jinja (backslash escaping):
    # render the real fact task with ansible-playbook and check the account names.
    tasks = yaml.safe_load(open(TASK_FILE))
    (tmp_path / "facts.yml").write_text(yaml.safe_dump([t for t in tasks if "ansible.builtin.set_fact" in t]))
    lab_file = os.path.abspath("ad/GOAD-Mini-Base/data/config.json")
    (tmp_path / "play.yml").write_text(f"""
- hosts: localhost
  gather_facts: false
  tasks:
    - ansible.builtin.set_fact:
        lab: "{{{{ (lookup('file', '{lab_file}') | from_json).lab }}}}"
    - ansible.builtin.include_tasks: facts.yml
      vars: {{ setting_value: 2 }}
    - ansible.builtin.copy:
        content: "{{{{ tier_deny_network | to_json }}}}"
        dest: "{tmp_path}/out.json"
""")
    subprocess.run([ANSIBLE_PLAYBOOK, "-i", "localhost,", "-c", "local", str(tmp_path / "play.yml")],
                   check=True, capture_output=True)
    assert sorted(json.load(open(tmp_path / "out.json"))) == \
        ["SEVENKINGDOMS\\T0-Admins", "SEVENKINGDOMS\\T1-ServerAdmins"]


def test_user_right_tasks_retry_name_translation():
    # cross-forest names may not translate right after the reboot that precedes hardening.yml
    for task in yaml.safe_load(open(TASK_FILE)):
        if "ansible.windows.win_user_right" in task:
            assert task.get("retries", 0) >= 5 and task.get("delay", 0) >= 30
            assert task.get("until") == "tier_result is succeeded"
            assert task.get("register") == "tier_result"
