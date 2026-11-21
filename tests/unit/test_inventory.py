from goad.lab.definition import load_lab, shipped_lab
from goad.lab.inventory import render_inventory


def test_inventory_groups():
    inv = render_inventory(load_lab(shipped_lab('2domains')), '192.168.56')
    children = inv['all']['children']
    assert set(children['windows']['hosts']) == {'dc01', 'dc02', 'srv02'}
    assert set(children['dc']['hosts']) == {'dc01', 'dc02'}
    assert children['server']['hosts']['srv02'] == {'ansible_host': '192.168.56.22', 'hostname': 'castelblack',
                                                    'domain': 'north.sevenkingdoms.local'}
    assert children['windows']['vars']['ansible_connection'] == 'psrp'
    assert inv['all']['vars']['ansible_password'] == 'Aa1234567890!'
