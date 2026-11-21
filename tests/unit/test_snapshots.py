from datetime import datetime, timezone

import pytest

from goad import GoadError
from goad.host.runner import Result
from goad.lab.snapshots import delete, list_snapshots, reset, take
from goad.lab.definition import parse_lab
from goad.state import load_state, working_lab_path


@pytest.fixture(autouse=True)
def vm_defaults(fake, lab):
    """Every VM runs and lists only `base`; a respond() made in a test wins over the listSnapshots default."""
    fake.respond(lambda a: a[3] == 'list',
                 Result(0, 'Total running VMs: 3\n' + '\n'.join(lab.vms().values()), ''))
    default = (lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 1\nbase\n', ''))
    fake._responses.append(default)

    def respond(predicate, result):
        fake._responses.insert(len(fake._responses) - 1, (predicate, result))

    fake.respond = respond


def test_take_records_lab_yml(lab, fake):
    record = take(lab, 'before-adcs')
    assert record.name == 'before-adcs' and record.lab_yml == working_lab_path(lab.settings).read_text()
    assert [a[3] for a in fake.calls if a[3] in ('snapshot',)] == ['snapshot'] * 3
    assert lab.state.current == 'before-adcs' and load_state(lab.settings).snapshot('before-adcs')


def test_take_without_label_uses_timestamp(lab):
    record = take(lab, now=lambda tz=None: datetime(2026, 11, 21, 9, 5, 7, tzinfo=timezone.utc))
    assert record.name == 'snap-20261121-090507' and record.label == ''


@pytest.mark.parametrize('label', ['base', 'has space', '', 'before-adcs'])
def test_take_rejects_bad_names(lab, label):
    take(lab, 'before-adcs')
    with pytest.raises(GoadError):
        take(lab, label)


def test_delete_base_refused(lab):
    with pytest.raises(GoadError, match='protected'):
        delete(lab, 'base')


def test_delete_runs_only_where_listed(lab, fake):
    take(lab, 'x')
    fake.respond(lambda a: a[3] == 'listSnapshots' and 'srv02' in a[4], Result(0, 'Total snapshots: 1\nbase\n', ''))
    fake.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\nx\n', ''))
    delete(lab, 'x')
    assert len([a for a in fake.calls if a[3] == 'deleteSnapshot']) == 2
    assert lab.state.snapshot('x') is None and lab.state.current is None


def test_delete_unknown_refused(lab):
    with pytest.raises(GoadError, match='unknown'):
        delete(lab, 'nope')


def test_reset_refused_when_missing_on_a_vm(lab, fake):
    take(lab, 'x'); fake.calls.clear()
    fake.respond(lambda a: a[3] == 'listSnapshots' and 'srv02' in a[4], Result(0, 'Total snapshots: 1\nbase\n', ''))
    fake.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\nx\n', ''))
    with pytest.raises(GoadError, match='srv02'):
        reset(lab, 'x', wait=lambda e: None)
    assert not [a for a in fake.calls if a[3] in ('stop', 'revertToSnapshot')]


def test_reset_restores_lab_yml(lab, fake):
    original = working_lab_path(lab.settings).read_text()
    working_lab_path(lab.settings).write_text(original.replace('1.1.1.1', '9.9.9.9'))
    lab.definition = parse_lab(working_lab_path(lab.settings).read_text(), 'edited')
    assert lab.definition.dns_forwarder == '9.9.9.9'
    reset(lab, wait=lambda e: None)
    assert working_lab_path(lab.settings).read_text() == original
    assert lab.definition.dns_forwarder == '1.1.1.1'
    assert [a[5] for a in fake.calls if a[3] == 'stop'] == ['hard'] * 3
    assert sorted(a[5] for a in fake.calls if a[3] == 'revertToSnapshot') == ['base'] * 3


def test_list_reports_missing(lab, fake):
    take(lab, 'x')
    fake.respond(lambda a: a[3] == 'listSnapshots' and 'srv02' in a[4], Result(0, 'Total snapshots: 1\nbase\n', ''))
    fake.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\nx\n', ''))
    rows = {r.record.name: r.missing_on for r in list_snapshots(lab)}
    assert rows == {'base': [], 'x': ['srv02']}


def test_take_failure_leaves_no_record_and_restarts(lab, fake):
    before = load_state(lab.settings)
    fake.respond(lambda a: a[3] == 'snapshot' and 'srv02' in a[4], Result(1, 'Error: disk full', ''))
    with pytest.raises(GoadError, match='srv02'):
        take(lab, 'x')
    assert lab.state.snapshot('x') is None and load_state(lab.settings) == before
    assert len([a for a in fake.calls if a[3] == 'deleteSnapshot']) == 2
    assert not [a for a in fake.calls if a[3] == 'deleteSnapshot' and 'srv02' in a[4]]


def test_take_failure_starts_stopped_vms(lab, fake):
    fake.respond(lambda a: a[3] == 'snapshot' and 'srv02' in a[4], Result(1, 'Error: disk full', ''))
    fake._responses.insert(0, (lambda a: a[3] == 'list', Result(0, 'Total running VMs: 0\n', '')))
    with pytest.raises(GoadError):
        take(lab, 'x')
    assert len([a for a in fake.calls if a[3] == 'start']) == 3


def test_reset_revert_failure_names_vms_and_keeps_state(lab, fake):
    original = working_lab_path(lab.settings).read_text()
    take(lab, 'x')
    fake.calls.clear()
    fake.respond(lambda a: a[3] == 'revertToSnapshot' and 'srv02' in a[4], Result(1, 'Error: busy', ''))
    fake.respond(lambda a: a[3] == 'listSnapshots', Result(0, 'Total snapshots: 2\nbase\nx\n', ''))
    with pytest.raises(GoadError, match='goad lab reset base') as info:
        reset(lab, wait=lambda e: None)
    assert 'srv02' in str(info.value)
    assert lab.state.current == 'x' and working_lab_path(lab.settings).read_text() == original
    assert not [a for a in fake.calls if a[3] == 'start']


def without_srv02(text):
    import yaml
    data = yaml.safe_load(text)
    data['hosts'].pop('srv02')
    return yaml.safe_dump(data)


def test_take_refuses_incompatible_working_copy(lab, fake):
    path = working_lab_path(lab.settings)
    path.write_text(without_srv02(path.read_text()))
    lab.definition = parse_lab(path.read_text(), 'edited')
    with pytest.raises(GoadError, match='srv02 was removed'):
        take(lab, 'x')
    assert fake.calls == [] and lab.state.snapshot('x') is None


def test_reset_refuses_incompatible_record(lab, fake):
    take(lab, 'x')
    lab.state.snapshot('x').lab_yml = without_srv02(lab.state.snapshot('x').lab_yml)
    fake.calls.clear()
    with pytest.raises(GoadError, match='srv02 was removed'):
        reset(lab, 'x', wait=lambda e: None)
    assert fake.calls == []
