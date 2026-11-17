# Kali extension

- Extension Name: kali
- Description: Add a Kali attacker box on the lab network (not domain joined)
- Machine name : {{lab_name}}-KALI
- Compatible with labs : *
- Providers : virtualbox, vmware (Vagrant only)

## Machine

- box: kalilinux/rolling
- ip: {{ip_range}}.99
- 2 CPU, 4096 MB
- ssh forwarded on host port 2299

## Install

```
instance_id> install_extension kali
```

- DNS: the lab domain controllers first, then the lab dns forwarder
- /etc/hosts: one line per lab host
- /etc/krb5.conf: one realm per lab domain
- kali-linux-default installed when missing
- the box is NOT joined to any domain

## Uninstall

- Not implemented yet
