import os
import re
import shutil
import subprocess

import pytest
import yaml

from goad.host.paths import ansible_bin
from goad.lab.definition import LAB_NAMES, REPO, load_lab, shipped_lab
from goad.lab.inventory import render_inventory
from goad.lab.provision import ANSIBLE_ENV
from goad.lab.settings_catalog import SETTINGS

ANSIBLE = REPO / 'ansible'
PLAYS = ['common', 'forest', 'child', 'trust', 'join and content', 'foreign members', 'post-join', 'settings']


def test_play_order():
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    assert [p['name'] for p in plays] == PLAYS
    assert [p['hosts'] for p in plays] == ['windows', 'forest_root', 'child_dc:ca_host', 'dc', 'dc:member', 'dc', 'windows', 'windows']
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


def test_connect_laps_read_survives_an_unreachable_dc():
    # An unreachable delegate marks the member unreachable; failed_when cannot cover it, and
    # ansible-core skips retries/until on a connection failure, so the DC is awaited first.
    tasks = {t['name']: t for t in yaml.safe_load((ANSIBLE / 'roles' / 'connect' / 'tasks' / 'main.yml').read_text())}
    wait = tasks['Wait for the DC before reading the Windows LAPS password']
    read = tasks['Read the Windows LAPS password of the host from its DC']
    names = list(tasks)
    assert names.index(wait['name']) < names.index(read['name'])
    for task in (wait, read):
        assert task['delegate_to'] == '{{ goad_domains[domain].dc }}'
        assert task.get('ignore_unreachable') is True
        assert task.get('ignore_errors') is True
    assert 'ansible.builtin.wait_for_connection' in wait and wait['ansible.builtin.wait_for_connection']['timeout'] > 0
    assert read['retries'] > 0 and read['delay'] > 0 and read['until'] == 'laps_login is succeeded'
    assert 'laps_dc is not skipped' in read['when']


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


def test_every_setting_has_a_task_file():
    files = {p.stem for p in (ANSIBLE / 'roles' / 'settings' / 'tasks').glob('*.yml')} - {'main'}
    assert files == {key.replace('.', '_') for key in SETTINGS}


def test_settings_files_have_no_become_or_assert():
    for path in (ANSIBLE / 'roles' / 'settings' / 'tasks').glob('*.yml'):
        text = path.read_text()
        assert 'ansible_become' not in text and 'ansible.builtin.assert' not in text, path


def test_settings_play_forces_handlers():
    # a reboot notified before a later task fails must still run: the re-run would not notify again
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'settings')
    assert play['force_handlers'] is True


def _module_keys(node):
    # every mapping key shaped like a fully qualified collection name: namespace.collection.module
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and re.fullmatch(r'[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+', key):
                yield key
            yield from _module_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _module_keys(item)


def test_modules_come_from_required_collections():
    # a fresh install only has ansible.builtin and the collections in requirements.yml
    required = {c['name'] for c in yaml.safe_load((ANSIBLE / 'requirements.yml').read_text())['collections']}
    allowed = required | {'ansible.builtin'}
    paths = [p for p in ANSIBLE.rglob('*.yml') if p.parent.name in ('tasks', 'handlers')] + [ANSIBLE / 'site.yml']
    for path in paths:
        for key in _module_keys(yaml.safe_load(path.read_text())):
            assert '.'.join(key.split('.')[:2]) in allowed, f'{path}: {key} not from {sorted(allowed)}'


def test_firewall_state_task_is_idempotent_powershell():
    task, = yaml.safe_load((ANSIBLE / 'roles' / 'settings' / 'tasks' / 'firewall_state.yml').read_text())
    module = task['ansible.windows.win_powershell']
    assert module['parameters'] == {'Wanted': '{{ setting_value }}'}
    script = module['script']
    assert '$Ansible.Changed = $false' in script and '$Ansible.Changed = $true' in script
    assert 'Domain, Private, Public' in script and 'Set-NetFirewallProfile' in script


def test_dns_record_cleanup_derives_subnet_from_the_lab_address():
    # the first IPv4 of the adapter can be 169.254.x: every lab record would look stale and go
    task, = yaml.safe_load((ANSIBLE / 'roles' / 'dc_dns' / 'tasks' / 'records.yml').read_text())
    module = task['ansible.windows.win_powershell']
    assert module['parameters']['LabAddress'] == '{{ ansible_host }}'
    assert 'Get-NetIPAddress -IPAddress $LabAddress' in module['script']
    assert 'Select-Object -First 1' not in module['script']


def test_connect_hides_the_laps_password():
    tasks = {t['name']: t for t in yaml.safe_load((ANSIBLE / 'roles' / 'connect' / 'tasks' / 'main.yml').read_text())}
    assert tasks['Read the Windows LAPS password of the host from its DC'].get('no_log') is True
    assert tasks['Use the Windows LAPS password for the local Administrator'].get('no_log') is True
    # no_log hides the failure text too: a separate task shows it, never the result
    report = tasks['Show why the Windows LAPS password read failed']
    assert 'laps_login is failed' in report['when']
    assert 'laps_login.msg' in report['ansible.builtin.debug']['msg'] and 'result' not in str(report)


def test_templates_do_not_ship_the_ca_role():
    script = (REPO / 'packer' / 'windows' / 'scripts' / 'install-features.ps1').read_text()
    assert 'ADCS-Cert-Authority' not in script
    assert 'RSAT-ADCS' in script and 'AD-Domain-Services' in script


def test_promotion_roles_keep_ca_removal():
    for role in ('forest', 'child_domain'):
        text = (ANSIBLE / 'roles' / role / 'tasks' / 'main.yml').read_text()
        assert 'Remove the certification authority role before promotion' in text


def test_child_play_hosts_include_ca_hosts():
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'child')
    assert play['hosts'] == 'child_dc:ca_host' and play['strategy'] == 'free'
    roles = {r['role']: r for r in play['roles']}
    assert list(roles) == ['child_domain', 'ca_feature']
    assert roles['ca_feature']['when'] == 'ca'


def test_ca_feature_tagged_adcs():
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'child')
    assert next(r for r in play['roles'] if r['role'] == 'ca_feature')['tags'] == ['adcs']


def test_adcs_role_no_longer_installs_the_feature():
    assert 'win_feature' not in (ANSIBLE / 'roles' / 'adcs' / 'tasks' / 'main.yml').read_text()
    assert 'ADCS-Cert-Authority' in (ANSIBLE / 'roles' / 'ca_feature' / 'tasks' / 'main.yml').read_text()


def _tasks(role: str) -> list:
    return yaml.safe_load((ANSIBLE / 'roles' / role / 'tasks' / 'main.yml').read_text())


def _task(role: str, name: str) -> dict:
    return next(t for t in _tasks(role) if t['name'] == name)


def test_ca_feature_tasks_run_only_when_certsvc_says_so():
    # win_feature takes minutes even when it has nothing to do: ask the CertSvc service first.
    for role in ('forest', 'child_domain'):
        check = _task(role, 'Check whether the host is a domain controller')
        assert 'CertSvc' in check['ansible.windows.win_powershell']['script']
        assert _task(role, 'Remove the certification authority role before promotion')['when'] == \
            'not dc_role.result.dc and dc_role.result.ca'
    assert 'CertSvc' in _tasks('ca_feature')[0]['ansible.windows.win_powershell']['script']


def test_trust_refreshes_name_routing_after_creation():
    names = [t['name'] for t in _tasks('trust')]
    assert names.index('Refresh forest trust name routing') > names.index('Bidirectional forest trust')
    task = _task('trust', 'Refresh forest trust name routing')
    script = task['ansible.windows.win_powershell']['script']
    assert '/dsgetfti:' in script and '/update_tdo' in script
    assert task['loop'] == '{{ goad_domains[domain].trusts }}'
    assert task['when'] == 'inventory_hostname in groups.forest_root'


def test_secure_channel_repair_does_not_count_as_a_change():
    # The repair fixes the login after a member booted before its DC; it changes no lab configuration,
    # so an unchanged lab still re-provisions with changed=0.
    assert _task('connect', 'Repair the secure channel of a joined host')['changed_when'] is False


def test_defender_feature_runs_only_when_the_service_is_missing():
    # win_feature takes minutes on a busy servicing stack even with nothing to do.
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'settings' / 'tasks' / 'defender_realtime.yml').read_text())
    check = tasks[0]
    assert 'WinDefend' in check['ansible.windows.win_powershell']['script']
    install = next(t for t in tasks if 'ansible.windows.win_feature' in t)
    assert install['when'] == 'defender_missing.result'


def test_ca_feature_installs_in_a_system_task_without_waiting():
    # The install takes up to 9 minutes on a just-promoted DC. A SYSTEM scheduled task lets it run
    # through the trust and join plays; Ansible async over PSRP fails when the session profile unloads.
    tasks = _tasks('ca_feature')
    assert [t['name'] for t in tasks] == ['Start the certification authority role install']
    script = tasks[0]['ansible.windows.win_powershell']['script']
    for needle in ('Register-ScheduledTask', "-User 'SYSTEM'", 'Install-WindowsFeature ADCS-Cert-Authority',
                   'ca-feature.json', 'CertSvc'):
        assert needle in script, needle
    assert 'async' not in tasks[0]


def test_adcs_waits_for_the_ca_feature_first():
    tasks = _tasks('adcs')
    wait = tasks[0]
    assert wait['name'] == 'Wait for the certification authority role install'
    assert 'ca-feature.json' in wait['ansible.windows.win_powershell']['script']
    assert wait['until'] == 'ca_wait is succeeded' and wait['retries'] * wait['delay'] >= 1200
    assert wait['changed_when'] is False
    assert tasks[1]['when'] == 'ca_wait.result.restart'


SETTINGS_TASKS = ANSIBLE / 'roles' / 'settings' / 'tasks'


@pytest.mark.parametrize('name, count', [('net_nbtns', 1), ('smb_signing', 1), ('ldap_signing', 1),
                                         ('kerberos_rc4', 1), ('smb_v1', 3)])
def test_settings_run_one_round_trip(name, count):
    # Each executed task costs 2-7 s per host; these settings ran 2 to 5 tasks on every run.
    tasks = yaml.safe_load((SETTINGS_TASKS / f'{name}.yml').read_text())
    assert len(tasks) == count, [t['name'] for t in tasks]
    assert not any('loop' in t for t in tasks)
    if name == 'smb_v1':   # the set task, a reboot only when needed, the set task again after a pending change
        assert [('ansible.windows.win_reboot' in t) for t in tasks] == [False, True, False]
        assert tasks[2]['when'] == 'smb_v1_set.result.pending'


def test_dc_gpo_helper_is_a_function_used_by_signing_settings():
    helper = (ANSIBLE / 'roles' / 'settings' / 'files' / 'dc_gpo.ps1').read_text()
    assert 'function Set-DcGpoValue' in helper and 'param(' not in helper.split('function', 1)[0]
    for name in ('smb_signing', 'ldap_signing'):
        text = (SETTINGS_TASKS / f'{name}.yml').read_text()
        assert "lookup('ansible.builtin.file', 'dc_gpo.ps1')" in text and 'Set-DcGpoValue' in text
    assert not (ANSIBLE / 'roles' / 'settings' / 'files' / 'set_dc_gpo_value.ps1').exists()
