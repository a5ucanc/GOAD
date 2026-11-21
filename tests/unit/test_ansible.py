import os
import shutil
import subprocess

import pytest
import yaml

from goad.host.paths import ansible_bin
from goad.lab.definition import LAB_NAMES, REPO, load_lab, shipped_lab
from goad.lab.inventory import render_inventory
from goad.lab.provision import ANSIBLE_ENV

ANSIBLE = REPO / 'ansible'
PLAYS = ['common', 'forest', 'child', 'trust', 'join and content', 'foreign members', 'post-join', 'settings']


def test_play_order():
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    assert [p['name'] for p in plays] == PLAYS
    assert [p['hosts'] for p in plays] == ['windows', 'forest_root', 'child_dc', 'dc', 'dc:member', 'dc', 'windows', 'windows']
    assert all(p['gather_facts'] is False for p in plays)


def test_no_fixed_waits():
    for path in ANSIBLE.rglob('*.yml'):
        text = path.read_text()
        for word in ('ansible.builtin.pause', 'Start-Sleep', 'post_reboot_delay', 'pre_reboot_delay'):
            assert word not in text, f'{path}: {word}'


@pytest.mark.skipif(shutil.which(ansible_bin('ansible-playbook')) is None, reason='ansible not installed')
@pytest.mark.parametrize('name', LAB_NAMES)
def test_site_syntax(name, tmp_path):
    inv = tmp_path / 'inventory.yml'
    inv.write_text(yaml.safe_dump(render_inventory(load_lab(shipped_lab(name)), '192.168.56')))
    result = subprocess.run([ansible_bin('ansible-playbook'), '--syntax-check', '-i', str(inv), str(ANSIBLE / 'site.yml')],
                            capture_output=True, text=True, env={**os.environ, **ANSIBLE_ENV})
    assert result.returncode == 0, result.stdout + result.stderr
