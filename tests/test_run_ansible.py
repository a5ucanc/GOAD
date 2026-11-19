import os
from types import SimpleNamespace

from goad.command import cmd as cmd_module
from goad.command.cmd import Command


def _capture_run(monkeypatch):
    seen = {}

    def fake_run(command, cwd=None, env=None, **kwargs):
        seen['command'] = command
        seen['cwd'] = cwd
        seen['env'] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cmd_module.subprocess, 'run', fake_run)
    return seen


def test_run_ansible_points_ansible_config_at_the_playbook_folder_cfg(tmp_path, monkeypatch):
    # ansible ignores an ansible.cfg in a world-writable cwd (WSL /mnt/c is 777),
    # so the folder cfg (roles_path...) must be passed explicitly.
    (tmp_path / 'ansible.cfg').write_text('[defaults]\nroles_path = ./roles\n')
    seen = _capture_run(monkeypatch)

    assert Command().run_ansible('-i inv install.yml', str(tmp_path)) is True

    assert seen['cwd'] == str(tmp_path)
    assert seen['env']['ANSIBLE_CONFIG'] == os.path.join(str(tmp_path), 'ansible.cfg')


def test_run_ansible_without_folder_cfg_keeps_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv('ANSIBLE_CONFIG', raising=False)
    seen = _capture_run(monkeypatch)

    Command().run_ansible('-i inv install.yml', str(tmp_path))

    assert seen['env'] is None or 'ANSIBLE_CONFIG' not in seen['env']


def test_run_ansible_keeps_an_ansible_config_set_by_the_user(tmp_path, monkeypatch):
    (tmp_path / 'ansible.cfg').write_text('[defaults]\n')
    monkeypatch.setenv('ANSIBLE_CONFIG', '/custom/ansible.cfg')
    seen = _capture_run(monkeypatch)

    Command().run_ansible('-i inv install.yml', str(tmp_path))

    assert seen['env'] is None or seen['env']['ANSIBLE_CONFIG'] == '/custom/ansible.cfg'
