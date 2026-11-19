# iis

- Extension name : `iis`
- Description : Install IIS on srv02 castelblack of a `-Base` lab (no new VM)
- Compatibility  : GOAD-Base / GOAD-Light-Base
- Providers : every provider of the lab (no VM)

- Hosts : srv02 castelblack
- Capabilities : `iis: [srv02]`

```
install_extension iis
remove_extension iis
```

`remove_extension iis` disables the enabled scenarios that need `iis` (it asks first), then removes the IIS features and deletes `C:\inetpub`.
