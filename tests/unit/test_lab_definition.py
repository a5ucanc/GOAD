import pytest
import yaml

from goad import GoadError
from goad.lab.definition import LAB_NAMES, load_lab, parse_lab, shipped_lab


def test_shipped_labs_load():
    for name in LAB_NAMES:
        lab = load_lab(shipped_lab(name))
        assert lab.name == name and lab.password == 'Aa1234567890!'


def test_2forests_host_map():
    lab = load_lab(shipped_lab('2forests'))
    assert {h: (d.hostname, d.octet, d.os) for h, d in lab.hosts.items()} == {
        'dc01': ('kingslanding', 10, 'win2025'), 'dc02': ('winterfell', 11, 'win2025'),
        'dc03': ('meereen', 12, 'win2025'), 'srv02': ('castelblack', 22, 'win2022'),
        'srv03': ('braavos', 23, 'win2022')}
    assert lab.domains['essos.local'].trust == 'sevenkingdoms.local'
    assert lab.templates_needed() == ['win2022', 'win2025']


def test_ip_and_dns():
    lab = load_lab(shipped_lab('2domains'))
    assert lab.ip('srv02', '10.0.5') == '10.0.5.22'
    assert lab.dns('dc01', '10.0.5') == ['10.0.5.10']
    assert lab.dns('dc02', '10.0.5') == ['10.0.5.10']   # child DC points at the parent DC
    assert lab.dns('srv02', '10.0.5') == ['10.0.5.11']


def test_unknown_shipped_lab_rejected():
    with pytest.raises(GoadError, match='nope'):
        shipped_lab('nope')


@pytest.mark.parametrize('mutate, message', [
    (lambda d: d['hosts']['srv02'].update(octet=10), 'octet'),
    (lambda d: d['hosts']['srv02'].update(octet=250), 'octet'),
    (lambda d: d['hosts']['srv02'].update(hostname='castelblack-north'), 'hostname'),
    (lambda d: d['hosts']['srv02'].update(hostname='KINGSLANDING'), 'hostname'),
    (lambda d: d['hosts']['srv02'].update(os='win10'), 'os'),
    (lambda d: d['hosts']['srv02'].update(role='linux'), 'role'),
    (lambda d: d['hosts']['srv02'].update(domain='nope.local'), 'domain'),
    (lambda d: d['hosts']['srv02'].update(colour='red'), 'colour'),
    (lambda d: d['hosts']['srv02'].pop('octet'), 'octet'),
    (lambda d: d['hosts']['srv02'].update(role='dc'), 'dc'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(dc='srv02'), 'dc'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(parent='nope.local'), 'parent'),
    (lambda d: d['domains']['north.sevenkingdoms.local'].update(trust='nope.local'), 'trust'),
    (lambda d: d.update(name='Two Domains'), 'name'),
    (lambda d: d.update(extra=1), 'extra'),
    (lambda d: d.pop('password'), 'password'),
])
def test_invalid_lab_rejected(mutate, message):
    data = yaml.safe_load(shipped_lab('2domains').read_text())
    mutate(data)
    with pytest.raises(GoadError, match=message):
        parse_lab(yaml.safe_dump(data), 'lab.yml')
