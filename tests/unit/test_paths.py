import pytest

from goad import GoadError
from goad.host.paths import to_windows, to_wsl


def test_to_windows_spaces():
    assert to_windows('/mnt/c/Program Files (x86)/VMware') == r'C:\Program Files (x86)\VMware'


def test_drive_root():
    assert to_windows('/mnt/d') == 'D:\\'
    assert str(to_wsl('D:\\')) == '/mnt/d'


def test_round_trip():
    assert to_windows(to_wsl(r'D:\goad\lab\dc01\dc01.vmx')) == r'D:\goad\lab\dc01\dc01.vmx'


def test_to_wsl_accepts_forward_slashes():
    assert str(to_wsl('C:/goad/templates')) == '/mnt/c/goad/templates'


def test_non_windows_path_rejected():
    with pytest.raises(GoadError):
        to_windows('/home/x/file')


def test_non_drive_windows_path_rejected():
    with pytest.raises(GoadError):
        to_wsl(r'\\server\share\x')
