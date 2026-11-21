import pypsrp.client
import pytest

from goad import GoadError
from goad.lab.remote import laps_password


class FakeClient:
    """pypsrp Client stand-in: records the connection and the script, returns a canned result."""
    result = ('', None, False)
    error = None
    calls = []

    def __init__(self, server, **kwargs):
        FakeClient.calls.append(('connect', server, kwargs))

    def execute_ps(self, script):
        FakeClient.calls.append(('script', script))
        if FakeClient.error is not None:
            raise FakeClient.error
        return FakeClient.result


@pytest.fixture
def client(monkeypatch):
    FakeClient.result, FakeClient.error, FakeClient.calls = ('', None, False), None, []
    monkeypatch.setattr(pypsrp.client, 'Client', FakeClient)
    return FakeClient


def test_laps_password_returns_stripped_output(client):
    client.result = ('  S3cret!pass\r\n', None, False)
    assert laps_password('10.0.5.12', 'Aa1234567890!', 'braavos') == 'S3cret!pass'
    (_, server, kwargs), (_, script) = client.calls
    assert server == '10.0.5.12' and kwargs['username'] == 'Administrator' and kwargs['password'] == 'Aa1234567890!'
    assert script == "(Get-LapsADPassword -Identity 'braavos' -AsPlainText).Password"


def test_laps_password_doubles_single_quotes_in_hostname(client):
    client.result = ('pw', None, False)
    laps_password('10.0.5.12', 'pw', "o'brien")
    assert client.calls[1][1] == "(Get-LapsADPassword -Identity 'o''brien' -AsPlainText).Password"


@pytest.mark.parametrize('result', [('', None, False), ('   \n', None, False), ('pw', None, True)])
def test_laps_password_refuses_empty_output_or_errors(client, result):
    client.result = result
    with pytest.raises(GoadError, match='no LAPS password for braavos'):
        laps_password('10.0.5.12', 'pw', 'braavos')


def test_laps_password_wraps_connection_failure(client):
    client.error = ConnectionError('refused')
    with pytest.raises(GoadError, match='no LAPS password for braavos') as info:
        laps_password('10.0.5.12', 'pw', 'braavos')
    assert isinstance(info.value.__cause__, ConnectionError)
