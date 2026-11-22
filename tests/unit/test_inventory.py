from goad.lab.definition import load_lab, shipped_lab
from goad.lab.inventory import render_inventory


def test_inventory_groups():
    inv = render_inventory(load_lab(shipped_lab('2domains')), '192.168.56')
    children = inv['all']['children']
    assert set(children['windows']['hosts']) == {'dc01', 'dc02', 'srv02'}
    assert set(children['dc']['hosts']) == {'dc01', 'dc02'}
    srv02 = children['server']['hosts']['srv02']
    assert {k: srv02[k] for k in ('ansible_host', 'hostname', 'domain')} == {
        'ansible_host': '192.168.56.22', 'hostname': 'castelblack', 'domain': 'north.sevenkingdoms.local'}
    assert children['windows']['vars']['ansible_connection'] == 'psrp'
    assert inv['all']['vars']['ansible_password'] == 'Aa1234567890!'


def test_inventory_member_connects_as_domain_admin():
    inv = render_inventory(load_lab(shipped_lab('2forests')), '192.168.56')
    srv03 = inv['all']['children']['member']['hosts']['srv03']
    assert srv03['ansible_user'] == 'ESSOS\\Administrator' and srv03['local_user'] == 'Administrator'
    assert srv03['laps'] is True and srv03['ca'] is True
    assert 'ansible_user' not in inv['all']['children']['dc']['hosts']['dc03']


def test_inventory_dc_dns():
    hosts = render_inventory(load_lab(shipped_lab('2forests')), '10.0.5')['all']['children']['dc']['hosts']
    assert hosts['dc01']['dc_dns'] == ['10.0.5.10'] and hosts['dc01']['dc_forwarder'] == '1.1.1.1'
    assert hosts['dc02']['dc_dns'] == ['10.0.5.11', '10.0.5.10'] and hosts['dc02']['dc_forwarder'] == '10.0.5.10'
    assert hosts['dc03']['laps_schema'] is True and hosts['dc01']['laps_schema'] is False


def test_inventory_domains():
    domains = render_inventory(load_lab(shipped_lab('2forests')), '192.168.56')['all']['vars']['goad_domains']
    assert domains['north.sevenkingdoms.local']['forest_root'] == 'sevenkingdoms.local'
    assert domains['essos.local']['trusts'] == ['sevenkingdoms.local'] and domains['sevenkingdoms.local']['trusts'] == ['essos.local']
    assert domains['essos.local']['trust'] == 'sevenkingdoms.local' and domains['sevenkingdoms.local']['trust'] is None
    assert domains['essos.local']['laps_hosts'] == ['braavos']
    assert {'name': 'tyron.lannister', 'domain': 'sevenkingdoms.local'} in domains['essos.local']['groups']['DragonsFriends']['members']
    assert domains['sevenkingdoms.local']['users']['tywin.lannister']['path'] == 'OU=Crownlands,DC=sevenkingdoms,DC=local'
    assert domains['sevenkingdoms.local']['dc_hostname'] == 'kingslanding.sevenkingdoms.local'


def test_inventory_play_groups():
    children = render_inventory(load_lab(shipped_lab('2forests')), '192.168.56')['all']['children']
    assert set(children['forest_root']['hosts']) == {'dc01', 'dc03'}
    assert set(children['child_dc']['hosts']) == {'dc02'}
    assert set(children['member']['hosts']) == {'srv02', 'srv03'}


def test_ca_host_group():
    children = render_inventory(load_lab(shipped_lab('2forests')), '192.168.56')['all']['children']
    assert set(children['ca_host']['hosts']) == {'dc01', 'srv03'}
    children = render_inventory(load_lab(shipped_lab('1domain')), '192.168.56')['all']['children']
    assert set(children['ca_host']['hosts']) == {'dc01'}
    assert not children['child_dc']['hosts']
