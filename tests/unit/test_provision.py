import pytest
import yaml

from goad import GoadError
from goad.host.runner import Result
from goad.lab.definition import load_lab, parse_lab
from goad.lab.provision import check_compatible, provision
from goad.state import inventory_path, working_lab_path


def test_provision_skips_without_playbook(settings, fake, deployed, tmp_path):
    lab = load_lab(working_lab_path(settings))
    assert provision(settings, fake, lab, deployed, playbook=tmp_path / 'none.yml') is False
    assert fake.calls == []


def test_provision_runs_with_tags(settings, fake, deployed, tmp_path):
    playbook = tmp_path / 'site.yml'
    playbook.write_text('[]')
    lab = load_lab(working_lab_path(settings))
    assert provision(settings, fake, lab, deployed, tags=['users', 'acl'], playbook=playbook) is True
    assert fake.calls == [['ansible-playbook', '-i', str(inventory_path(settings)), '-f', '3', str(playbook),
                           '--tags', 'users,acl']]


def test_provision_failure_names_log(settings, fake, deployed, tmp_path):
    playbook = tmp_path / 'site.yml'
    playbook.write_text('[]')
    fake.respond(lambda a: a[0] == 'ansible-playbook', Result(2, '', ''))
    with pytest.raises(GoadError, match=r'exit 2.*provision-'):
        provision(settings, fake, load_lab(working_lab_path(settings)), deployed, playbook=playbook)


@pytest.mark.parametrize('edit, message', [
    (lambda d: d['hosts'].pop('srv02'), 'srv02'),
    (lambda d: d['hosts']['srv02'].update(octet=30), 'srv02.*ip'),
    (lambda d: d['hosts']['srv02'].update(os='win2025'), 'srv02.*os'),
    (lambda d: d['hosts']['srv02'].update(hostname='other'), 'srv02.*hostname'),
])
def test_incompatible_working_copy_refused(settings, deployed, edit, message):
    data = yaml.safe_load(working_lab_path(settings).read_text())
    edit(data)
    with pytest.raises(GoadError, match=message):
        check_compatible(parse_lab(yaml.safe_dump(data), 'lab.yml'), deployed)
