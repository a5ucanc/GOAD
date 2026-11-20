import pytest

from goad import GoadError
from goad.vmware.parallel import run_parallel

VMS = {'dc01': 1, 'dc02': 2, 'srv02': 3}


def test_all_ok():
    seen = []
    result = run_parallel(VMS, lambda name, value: seen.append((name, value)), 'snapshot')
    assert sorted(result.ok) == ['dc01', 'dc02', 'srv02'] and result.failed == {}
    assert sorted(seen) == [('dc01', 1), ('dc02', 2), ('srv02', 3)]
    result.raise_if_failed('snapshot')


def test_one_failure_others_still_run():
    seen = []

    def fn(name, value):
        if name == 'dc02':
            raise GoadError('vmrun snapshot failed: disk full')
        seen.append(name)
    result = run_parallel(VMS, fn, 'snapshot')
    assert sorted(result.ok) == ['dc01', 'srv02'] and sorted(seen) == ['dc01', 'srv02']
    assert 'disk full' in result.failed['dc02']


def test_unexpected_exception_is_recorded():
    def fn(name, value):
        raise RuntimeError('kaboom')
    result = run_parallel({'dc01': 1}, fn, 'start')
    assert 'kaboom' in result.failed['dc01']


def test_raise_if_failed_names_every_vm():
    def fn(name, value):
        if name != 'srv02':
            raise GoadError(f'{name} broke')
    with pytest.raises(GoadError) as e:
        run_parallel(VMS, fn, 'revert').raise_if_failed('revert')
    assert 'dc01' in str(e.value) and 'dc02' in str(e.value) and str(e.value).startswith('revert failed on')
