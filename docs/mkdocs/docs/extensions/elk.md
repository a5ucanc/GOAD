# elk

- Extension name : `elk`
- Compatibility  : `*`
- Providers : virtualbox/azure/vmware/aws/ludus
- Add a machine  : elk  (ip_range.50)

- Kibana (Elastic 9.x) is configured on http://{{ip_range}}.50:5601 to follow the lab events
- Kibana login : `elastic` / `Aa1234567890!` (change it with `elk_elastic_password` in the elk role defaults)
- Infos : log encyclopedia : https://www.ultimatewindowssecurity.com/securitylog/encyclopedia/
- Install winlogbeat and sysmon on domain computer machines

## prerequisites

- You need `sshpass` for the elk installation
```bash
sudo apt install sshpass
```

- On ludus prepare template :
```
ludus templates add -d ubuntu-22.04-x64-server
ludus templates build
```

## Install

- select your instance
```
load <instance_id>
```

- install the elk extension
```
install_extension elk
```


