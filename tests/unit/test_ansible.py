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
PLAYS = ['common', 'forest', 'child', 'trust', 'join and content', 'foreign members', 'post-join', 'settings',
         'services']


def test_play_order():
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    assert [p['name'] for p in plays] == PLAYS
    assert [p['hosts'] for p in plays] == ['windows', 'forest_root', 'child_dc', 'dc', 'dc:member', 'dc', 'windows', 'windows',
                                                'windows']
    assert all(p['gather_facts'] is False for p in plays)


def test_no_fixed_waits():
    for path in ANSIBLE.rglob('*.yml'):
        text = path.read_text()
        for word in ('ansible.builtin.pause', 'Start-Sleep', 'post_reboot_delay', 'pre_reboot_delay'):
            assert word not in text, f'{path}: {word}'


@pytest.mark.skipif(shutil.which(ansible_bin('ansible-playbook')) is None, reason='ansible not installed')
@pytest.mark.parametrize('name', LAB_NAMES)
@pytest.mark.parametrize('extensions', ['', 'extensions: [mssql, iis]\n'])
def test_site_syntax(name, extensions, tmp_path):
    from goad.lab.definition import parse_lab
    inv = tmp_path / 'inventory.yml'
    lab = parse_lab(shipped_lab(name).read_text() + extensions, name)
    inv.write_text(yaml.safe_dump(render_inventory(lab, '192.168.56')))
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
    assert names == ['laps_schema', 'laps_dc', 'local_groups', 'laps_host']


def test_settings_play_starts_with_adcs():
    # post-join is linear: the CA wait there held every host. The settings play is free, so the other
    # hosts apply their settings while the CA host waits for its role install.
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'settings')
    assert play['strategy'] == 'free'
    assert play['roles'][0] == {'role': 'adcs', 'when': 'ca', 'tags': ['adcs']}
    assert play['roles'][1:] == ['settings']


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


def test_ca_feature_starts_after_the_child_promotion():
    # Started beside the child promotion, the install slowed the promotion (it replicates from the
    # parent DC) from 3.6 to 8 minutes: it starts in the join and content play instead.
    plays = yaml.safe_load((ANSIBLE / 'site.yml').read_text())
    child = next(p for p in plays if p['name'] == 'child')
    assert child['hosts'] == 'child_dc' and child['roles'] == ['child_domain']
    join = next(p for p in plays if p['name'] == 'join and content')
    roles = [r['role'] for r in join['roles']]
    assert roles == ['join', 'ca_feature', 'ad_content']
    ca = join['roles'][1]
    assert ca['when'] == 'ca' and ca['tags'] == ['adcs']


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
    assert wait['retries'] * wait['delay'] >= 1200
    assert wait['changed_when'] is False
    assert tasks[2]['when'] == 'ca_wait.result.restart'


def test_adcs_wait_retries_only_while_the_install_runs():
    # A failed or missing install is terminal: retrying it hid the install error behind 20 minutes of
    # "no install is running". Transport failures (result missing) are still retried.
    tasks = _tasks('adcs')
    wait, report = tasks[0], tasks[1]
    script = wait['ansible.windows.win_powershell']['script']
    assert wait['until'] == "ca_wait is succeeded and ca_wait.result.state != 'running'"
    assert 'throw' not in script
    for state in ('running', 'done', 'failed', 'missing'):
        assert f"state = '{state}'" in script, state
    assert report['ansible.builtin.fail']['msg'] == '{{ ca_wait.result.error }}'
    assert report['when'] == "ca_wait.result.state in ['failed', 'missing']"


def test_ca_tasks_treat_only_a_running_task_as_an_install_under_way():
    # A VM that restarts during the install leaves the task registered, not running, with no result.
    # Counting that as "under way" blocked the CA for good: both scripts unregister such a task.
    for script in (_tasks('ca_feature')[0]['ansible.windows.win_powershell']['script'],
                   _tasks('adcs')[0]['ansible.windows.win_powershell']['script']):
        assert ".State -eq 'Running'" in script
        assert 'Unregister-ScheduledTask' in script


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


def test_join_reboots_in_its_own_task():
    # microsoft.ad treats a connection failure while it sends shutdown.exe as a started reboot. The join
    # can drop the PSRP connection (network profile switch): the reboot never ran and the task waited
    # 600 s for a boot time change. A separate task opens a fresh connection first.
    tasks = _tasks('join')
    join = _task('join', 'Join the domain')
    assert join['microsoft.ad.membership']['reboot'] is False and join['register'] == 'join_result'
    reboot = tasks[tasks.index(join) + 1]
    assert 'ansible.windows.win_reboot' in reboot and reboot['when'] == 'join_result.reboot_required'


def test_computer_delegation_runs_after_join():
    # The join and content play is free: a DC may reach ad_content before a member has joined,
    # so computer-account delegation runs in the linear foreign members play that follows it.
    plays = {p['name']: p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text())}
    assert plays['foreign members']['roles'] == ['foreign_members', 'ad_computers', 'ad_acls']
    accounts = (ANSIBLE / 'roles' / 'ad_content' / 'tasks' / 'accounts.yml').read_text()
    assert 'Computer delegation' not in accounts


def test_preauth_task_skips_entries_that_keep_preauth():
    task = next(t for t in _tasks_file('ad_content', 'accounts') if 'pre-authentication' in t['name'])
    assert "rejectattr('value.preauth')" in task['loop']


def _tasks_file(role: str, name: str) -> list:
    return yaml.safe_load((ANSIBLE / 'roles' / role / 'tasks' / f'{name}.yml').read_text())


def test_gpos_created_last_in_ad_content():
    tasks = _tasks_file('ad_content', 'main')
    assert tasks[-1]['ansible.builtin.include_tasks'] == 'gpos.yml'
    gpos = _tasks_file('ad_content', 'gpos')
    assert len(gpos) == 1 and "goad_domains[domain].gpos | default({})" in gpos[0]['loop']
    script = gpos[0]['ansible.windows.win_powershell']['script']
    assert 'New-GPO' in script and 'New-GPLink' in script and 'Set-GPPermission' not in script


def test_ad_acls_tasks():
    tasks = _tasks_file('ad_acls', 'main')
    by_name = {t['name']: t for t in tasks}
    aces = by_name['ACEs']
    assert "lookup('ansible.builtin.file', 'ace.ps1')" in aces['ansible.windows.win_powershell']['script']
    assert set(aces['ansible.windows.win_powershell']['parameters']) == {'Principal', 'Kind', 'Name', 'Right', 'Inherit'}
    assert "goad_domains[domain].acls | default([])" in aces['loop']
    assert "'template'" in aces['loop'] and "'gpo'" in aces['loop']
    gpo = by_name['GPO permissions']
    assert 'GpoEditDeleteModifySecurity' in gpo['ansible.windows.win_powershell']['script']
    assert "selectattr('kind', 'equalto', 'gpo')" in gpo['loop']
    sdprop = by_name['Run SDProp after an AdminSDHolder change']
    assert 'runProtectAdminGroupsTask' in sdprop['ansible.windows.win_powershell']['script']
    assert "'adminsdholder'" in sdprop['when']
    ace = (ANSIBLE / 'roles' / 'ad_acls' / 'files' / 'ace.ps1').read_text()
    for guid in ('bf9679c0-0de6-11d0-a285-00aa003049e2', 'f3a64788-5306-11d1-a9c5-0000f80367c1',
                 '00299570-246d-11d0-a768-00aa006e0529'):
        assert guid in ace
    for text in ('CN=AdminSDHolder,CN=System,', 'CN=Certificate Templates,CN=Public Key Services,CN=Services,',
                 'GenericExecute', 'ReadProperty'):
        assert text in ace
    assert 'RemoveAccessRule' not in ace


def test_adcs_templates_run_last_after_the_ca():
    tasks = _tasks('adcs')
    assert tasks[-1]['ansible.builtin.include_tasks'] == 'templates.yml'
    assert tasks[-2]['name'] == 'Enterprise root certification authority'
    steps = yaml.safe_load((ANSIBLE / 'roles' / 'adcs' / 'tasks' / 'templates.yml').read_text())
    assert [t['name'] for t in steps] == [
        'ADCSTemplate module', 'Create and publish certificate templates', 'Template enroll rights',
        'Issuance policies', 'CA ACL', 'Template ACEs']
    for t in steps:
        if t['name'] != 'CA ACL':  # registry of the CA host itself
            assert t['delegate_to'] == '{{ goad_domains[domain].dc }}', t['name']
    ace = "{{ lookup('ansible.builtin.file', role_path ~ '/../ad_acls/files/ace.ps1') }}"
    assert steps[2]['ansible.windows.win_powershell']['script'] == ace
    assert steps[5]['ansible.windows.win_powershell']['script'] == ace
    assert all('PSPKI' not in t['ansible.windows.win_powershell']['script'] for t in steps[1:])


def test_ace_script_knows_enroll_but_lab_acls_do_not():
    from goad.lab.definition import ACL_RIGHTS
    assert "'Enroll'" in (ANSIBLE / 'roles' / 'ad_acls' / 'files' / 'ace.ps1').read_text()
    assert '0e10c968-78fb-11d2-90d4-00c04f79dc55' in (ANSIBLE / 'roles' / 'ad_acls' / 'files' / 'ace.ps1').read_text()
    assert 'Enroll' not in ACL_RIGHTS


def test_services_play():
    play = next(p for p in yaml.safe_load((ANSIBLE / 'site.yml').read_text()) if p['name'] == 'services')
    assert play['hosts'] == 'windows' and play['tags'] == ['services']
    roles = {r['role']: r for r in play['roles']}
    assert list(roles) == ['mssql', 'iis']
    assert "'mssql' in services" in roles['mssql']['when'] and "'iis' in services" in roles['iis']['when']


def test_scenario_replay_runs_services():
    from goad.lab.scenario_ops import ENABLE_TAGS
    assert 'services' in ENABLE_TAGS


def test_iis_installs_no_dotnet35():
    # ASP.NET 3.5 needs NET-Framework-Core, whose payload comes from Windows Update (fails behind TLS inspection)
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'iis' / 'tasks' / 'main.yml').read_text())
    features = [t['ansible.windows.win_feature'] for t in tasks if 'ansible.windows.win_feature' in t]
    names = [n for f in features for n in f['name']]
    assert 'Web-Asp-Net45' in names
    assert not any(f.get('include_sub_features') for f in features)
    assert not {'Web-Asp-Net', 'Web-Net-Ext', 'NET-Framework-Core', 'NET-Framework-Features'} & set(names)


def test_mssql_installers_accept_reboot_pending():
    for name in ('install.yml', 'ssms.yml'):
        text = (ANSIBLE / 'roles' / 'mssql' / 'tasks' / name).read_text()
        assert 'rc not in [0, 3010]' in text, name


def test_mssql_options_failure_is_reported_without_no_log():
    tasks = yaml.safe_load((ANSIBLE / 'roles' / 'mssql' / 'tasks' / 'main.yml').read_text())
    names = [t['name'] for t in tasks]
    options = tasks[names.index('Apply the sa login and the scenario options')]
    report = tasks[names.index('Apply the sa login and the scenario options') + 1]
    assert options['no_log'] is True and options['failed_when'] is False
    assert 'ansible.builtin.fail' in report and 'no_log' not in report
    assert 'mssql_options.result.error' in report['ansible.builtin.fail']['msg']
