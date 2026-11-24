import pytest

from goad.host.runner import Result
from goad.vmware.vmrun import VmrunError

VMRUN = '/mnt/c/Program Files (x86)/VMware/VMware Workstation/vmrun.exe'


def test_clone_argv(vmrun, fake):
    vmrun.clone_linked(r'C:\t\win2025-v1\win2025-v1.vmx', r'C:\goad\lab\dc01\dc01.vmx', 'base', 'lab-dc01')
    assert fake.calls[-1] == [VMRUN, '-T', 'ws', 'clone', r'C:\t\win2025-v1\win2025-v1.vmx',
                              r'C:\goad\lab\dc01\dc01.vmx', 'linked', '-snapshot=base', '-cloneName=lab-dc01']


def test_start_and_stop_argv(vmrun, fake):
    vmrun.start('a.vmx')
    vmrun.stop('a.vmx')
    vmrun.stop('a.vmx', hard=True)
    assert [c[3:] for c in fake.calls] == [['start', 'a.vmx', 'nogui'], ['stop', 'a.vmx', 'soft'], ['stop', 'a.vmx', 'hard']]


def test_error_on_stdout_with_exit_zero(vmrun, fake):
    fake.respond(lambda a: 'revertToSnapshot' in a, Result(0, 'Error: A snapshot with the name does not exist', ''))
    with pytest.raises(VmrunError, match='does not exist'):
        vmrun.revert('x.vmx', 'base')


def test_nonzero_exit_raises(vmrun, fake):
    fake.respond(lambda a: 'snapshot' in a, Result(255, '', 'boom'))
    with pytest.raises(VmrunError, match='boom'):
        vmrun.snapshot('x.vmx', 'base')


def test_running_parses_list(vmrun, fake):
    fake.respond(lambda a: 'list' in a, Result(0, 'Total running VMs: 1\r\nC:\\goad\\lab\\DC01\\dc01.vmx\r\n', ''))
    assert vmrun.running() == ['c:/goad/lab/dc01/dc01.vmx']


def test_snapshots_parses_list(vmrun, fake):
    fake.respond(lambda a: 'listSnapshots' in a, Result(0, 'Total snapshots: 2\nbase\ncp1\n', ''))
    assert vmrun.snapshots('x.vmx') == ['base', 'cp1']


def test_read_guest_var_unset_returns_empty(vmrun, fake):
    assert vmrun.read_guest_var('x.vmx', 'goad.firstboot') == ''
    assert fake.calls[-1][3:] == ['readVariable', 'x.vmx', 'guestVar', 'goad.firstboot']


def test_delete_vm_argv(vmrun, fake):
    vmrun.delete_vm('x.vmx')
    assert fake.calls[-1][3:] == ['deleteVM', 'x.vmx']


def test_guest_ops_argv(vmrun, fake):
    vmrun.copy_to_guest('a.vmx', 'kali', 'pw', r'C:\x\prep.sh', '/tmp/prep.sh')
    vmrun.run_in_guest('a.vmx', 'kali', 'pw', '/bin/bash', ['/tmp/prep.sh', 'pw'], timeout=99)
    assert [c[3:] for c in fake.calls] == [
        ['-gu', 'kali', '-gp', 'pw', 'copyFileFromHostToGuest', 'a.vmx', r'C:\x\prep.sh', '/tmp/prep.sh'],
        ['-gu', 'kali', '-gp', 'pw', 'runProgramInGuest', 'a.vmx', '/bin/bash', '/tmp/prep.sh', 'pw']]


def test_guest_op_failure_names_command(vmrun, fake):
    fake.respond(lambda a: 'runProgramInGuest' in a, Result(0, 'Error: Guest program exited with non-zero exit code: 1', ''))
    with pytest.raises(VmrunError, match='vmrun runProgramInGuest failed: Error: Guest program exited'):
        vmrun.run_in_guest('a.vmx', 'kali', 'pw', '/bin/bash', [])


def test_tools_state(vmrun, fake):
    fake.respond(lambda a: 'checkToolsState' in a, Result(0, 'running\r\n', ''))
    assert vmrun.tools_state('a.vmx') == 'running'
    assert fake.calls[-1][3:] == ['checkToolsState', 'a.vmx']


def test_reset_argv(vmrun, fake):
    vmrun.reset('a.vmx', hard=True)
    assert [c[3:] for c in fake.calls] == [['reset', 'a.vmx', 'hard']]
