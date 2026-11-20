import hashlib

import pytest

from goad import GoadError
from goad.host.runner import Result
from goad.settings import IsoSource
from goad.templates.iso import ensure_iso


@pytest.fixture
def iso_dir(tmp_path, monkeypatch):
    folder = tmp_path / 'iso'
    monkeypatch.setattr('goad.templates.iso.local_dir', lambda windows_path: folder)
    return folder


def _download_writes(fake, iso_dir, data=b'iso-bytes', code=0):
    def on_curl(argv):
        if argv[0] == 'curl.exe':
            iso_dir.mkdir(parents=True, exist_ok=True)
            (iso_dir / 'win2025.iso.part').write_bytes(data)
            return True
        return False
    fake.respond(on_curl, Result(code, '', 'curl: (18) transfer closed' if code else ''))


def test_local_path_passes_through(settings, fake, iso_dir):
    settings.isos['win2025'] = IsoSource(r'D:\iso\2025.iso', 'none')
    assert ensure_iso('win2025', settings, fake) == (r'D:\iso\2025.iso', 'none')
    assert fake.calls == []


def test_pinned_checksum_url_passes_through(settings, fake, iso_dir):
    assert ensure_iso('ubuntu2404', settings, fake)[1].startswith('sha256:')
    assert fake.calls == []


def test_download_resumable_and_hashed(settings, fake, iso_dir):
    _download_writes(fake, iso_dir)
    path, checksum = ensure_iso('win2025', settings, fake)
    assert path == r'C:\goad\iso\win2025.iso'
    assert checksum == 'sha256:' + hashlib.sha256(b'iso-bytes').hexdigest()
    curl = fake.calls[0]
    assert curl[:2] == ['curl.exe', '-L'] and '--fail' in curl and '-C' in curl and '--retry' in curl
    assert curl[curl.index('-o') + 1] == r'C:\goad\iso\win2025.iso.part'
    assert (iso_dir / 'win2025.iso').read_bytes() == b'iso-bytes'
    assert not (iso_dir / 'win2025.iso.part').exists()


def test_second_call_reuses_download(settings, fake, iso_dir):
    _download_writes(fake, iso_dir)
    first = ensure_iso('win2025', settings, fake)
    calls = len(fake.calls)
    assert ensure_iso('win2025', settings, fake) == first
    assert len(fake.calls) == calls


def test_failed_download_keeps_part_and_raises(settings, fake, iso_dir):
    _download_writes(fake, iso_dir, code=18)
    with pytest.raises(GoadError, match='download of win2025 ISO failed'):
        ensure_iso('win2025', settings, fake)
    assert not (iso_dir / 'win2025.iso').exists()
    assert (iso_dir / 'win2025.iso.part').exists()  # resumed next time
