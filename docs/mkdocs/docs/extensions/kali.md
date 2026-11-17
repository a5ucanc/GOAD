# kali

- Extension name : `kali`
- Description : Add a Kali attacker box on the lab network (not domain joined)
- Compatibility : all labs
- Providers : virtualbox, vmware (Vagrant only)

- Add a machine : {{lab_name}}-KALI (ip_range.99)

## Machine

- Box: `kalilinux/rolling`
- IP: `{{ip_range}}.99`
- 2 CPU, 4096 MB
- SSH forwarded on host port 2299

## Install

```
instance_id> install_extension kali
```

The provisioning configures:

- DNS: the lab domain controllers first, then the lab DNS forwarder
- `/etc/hosts`: one line per lab host
- `/etc/krb5.conf`: one realm per lab domain
- `kali-linux-default`, installed when missing

The box is not joined to any domain.

!!! note "uninstall"
    Uninstall is not implemented yet.

It pairs well with the [vulnerability scenarios](../scenarios.md): enable a scenario, then attack it from the Kali box.
