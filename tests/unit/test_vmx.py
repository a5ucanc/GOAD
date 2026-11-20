from goad.vmware.vmx import Vmx

SAMPLE = '.encoding = "windows-1252"\n# comment line\nmemSize = "2048"\nnumvcpus = "2"\n'


def test_roundtrip_preserves_order_and_comments(tmp_path):
    f = tmp_path / 'a.vmx'
    f.write_text(SAMPLE)
    vmx = Vmx.load(f)
    vmx['guestinfo.goad.ip'] = '192.168.56.10'
    vmx.save()
    lines = f.read_text().splitlines()
    assert lines[:4] == SAMPLE.splitlines()
    assert lines[4] == 'guestinfo.goad.ip = "192.168.56.10"'


def test_case_insensitive(tmp_path):
    f = tmp_path / 'a.vmx'
    f.write_text(SAMPLE)
    vmx = Vmx.load(f)
    assert vmx['memsize'] == '2048'
    vmx['MEMSIZE'] = '4096'
    vmx.save()
    assert 'memSize = "4096"' in f.read_text().splitlines()


def test_delete_and_contains(tmp_path):
    f = tmp_path / 'a.vmx'
    f.write_text(SAMPLE)
    vmx = Vmx.load(f)
    del vmx['numvcpus']
    assert 'numvcpus' not in vmx and 'memsize' in vmx
    del vmx['absent']  # no error
    vmx.save()
    assert 'numvcpus' not in f.read_text()
