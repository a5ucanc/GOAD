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


def test_join_falls_back_only_when_unreachable():
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'connect' / 'tasks' / 'main.yml').read_text())
    probe, fallback = tasks[0], tasks[1]
    assert probe.get('ignore_unreachable') is True
    assert fallback['when'] == 'domain_login.unreachable | default(false)'


def test_connect_runs_first_on_every_run():
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    first = plays[0]['roles'][0]
    assert first['role'] == 'connect'
    assert 'always' in first['tags']


def test_content_order():
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'ad_content' / 'tasks' / 'main.yml').read_text())
    modules = [next(k for k in t if '.' in k and k.split('.')[0] in ('microsoft', 'ansible')) for t in tasks]
    assert modules.index('microsoft.ad.ou') < modules.index('microsoft.ad.group') < modules.index('microsoft.ad.user')


def test_parent_zone_cleanup_runs_after_child_play():
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    names = [p['name'] for p in plays]
    trust = plays[names.index('trust')]
    assert names.index('child') < names.index('trust')
    cleanup = trust['pre_tasks'][0]
    assert cleanup['ansible.builtin.include_role']['name'] == 'dc_dns'
    assert cleanup['ansible.builtin.include_role']['tasks_from'] == 'records'
    assert cleanup['when'] == 'inventory_hostname in groups.forest_root'
    main = yaml.safe_load((ANSIBLE / 'roles' / 'dc_dns' / 'tasks' / 'main.yml').read_text())
    assert {'ansible.builtin.import_tasks': 'records.yml'} in main


def test_no_reset_connection():
    # ansible-core ignores an inherited role `when` on meta reset_connection and resets every host
    for path in ANSIBLE.rglob('*.yml'):
        assert 'reset_connection' not in path.read_text(), path


def test_post_join_role_order():
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'post-join')
    names = [r['role'] if isinstance(r, dict) else r for r in play['roles']]
    assert names == ['laps_schema', 'laps_dc', 'local_groups', 'laps_host', 'adcs']


def test_laps_processing_reruns_without_password():
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'laps_host' / 'tasks' / 'main.yml').read_text())
    names = [t['name'] for t in tasks]
    probe = next(t for t in tasks if t.get('register') == 'laps_probe')
    invoke = next(t for t in tasks if 'Invoke-LapsPolicyProcessing' in t.get('ansible.windows.win_powershell', {}).get('script', ''))
    assert probe['failed_when'] is False and probe['changed_when'] is False
    assert probe['delegate_to'] == '{{ goad_domains[domain].dc }}'
    assert names.index(probe['name']) < names.index(invoke['name'])
    assert 'laps_policy is changed' in invoke['when'] and 'laps_probe' in invoke['when']
