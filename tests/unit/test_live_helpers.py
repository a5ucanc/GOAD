"""Live test helpers that need no lab: the logon wait."""
import pytest

import tests.live.helpers as helpers


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(helpers.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(helpers.time, 'sleep', lambda s: now.__setitem__(0, now[0] + s))
    return now


def test_wait_logon_retries_until_the_logon_works(monkeypatch, clock):
    answers = [RuntimeError('401'), RuntimeError('401'), 'kingslanding']

    def psrp(ip, user, script, password=helpers.PASSWORD):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(helpers, 'psrp', psrp)
    assert helpers.wait_logon('192.168.56.10', 'Administrator') == 2 * helpers.POLL
    assert answers == []


def test_wait_logon_reports_the_last_error_after_the_timeout(monkeypatch, clock):
    def psrp(ip, user, script, password=helpers.PASSWORD):
        raise RuntimeError('Failed to authenticate the user Administrator with ntlm')

    monkeypatch.setattr(helpers, 'psrp', psrp)
    with pytest.raises(AssertionError, match='192.168.56.10 as Administrator: no logon after 60 s: .*ntlm'):
        helpers.wait_logon('192.168.56.10', 'Administrator', timeout=60)
