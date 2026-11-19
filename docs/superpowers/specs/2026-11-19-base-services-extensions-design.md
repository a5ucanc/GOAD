# Base services as extensions

## Intent

The `*-Base` labs should hold only AD infrastructure: DCs, trusts, member servers, ADCS and LAPS. Application services (MSSQL, SSMS, IIS) are not infrastructure. They move out of the Base labs into opt-in extensions that install onto the existing Base hosts. Scenarios that need a service unlock only when the matching extension is installed on the instance.

## Goals

- GOAD-Base and GOAD-Light-Base deploy with no MSSQL, SSMS or IIS.
- An `mssql` extension installs SQL Server on existing Base hosts and grants the `mssql` / `mssql_link` capabilities.
- An `iis` extension installs IIS on srv02 and grants the `iis` capability.
- `mssql-sysadmin`, `mssql-impersonate-login`, `mssql-impersonate-user`, `mssql-linked` and `iis-upload` work on a Base instance once the matching extension is installed, and are refused before that.

## Non-goals

- Full GOAD, GOAD-Light, GOAD-Mini and GOAD-Mini-Base are unchanged (Mini-Base already has no services).
- The `exchange` extension is unchanged; it keeps its own VM (srv01 the-eyrie).
- No migration of already-deployed instances. They keep their state; the new layout needs a rebuild.
- `mssql-linked` is not offered on GOAD-Light-Base (no second forest SQL host).

## Approaches considered

1. **Dedicated services VM shared by extensions** (first extension deploys the VM, the others reuse it, through a hidden host extension or machine dedup). Rejected: adds a new VM and a new shared-machine mechanism, and `mssql-linked` still needed a second SQL host in essos.
2. **Scenarios install the service themselves.** Rejected: every MSSQL/IIS scenario would carry a full install, and uninstall would have to tear the service down.
3. **Extensions with no VM that install onto existing Base hosts (chosen).** srv02 castelblack and srv03 braavos already exist and already were the service hosts. No new VM, no new machine mechanism; extension playbooks already reach Base hosts (exchange's `install.yml` runs on dc01).

## Design

### Base labs (GOAD-Base, GOAD-Light-Base)

- `data/inventory`: empty the groups `iis`, `mssql`, `mssql_ssms`, `mssql_link`.
- `data/config.json`:
  - drop `iis`, `mssql`, `mssql_link` from `capabilities`;
  - drop the `mssql` blocks from host entries;
  - drop the `sql_svc` users from the domains (the extension creates them).
- README: services come from the `mssql` / `iis` extensions.
- Update tests that assert Base capabilities/inventory.

### `extensions/mssql` (no VM)

- `extension.json`: `"machines": []`, `"compatibility": ["GOAD-Base", "GOAD-Light-Base"]`, plus a per-lab `capabilities` map:
  - GOAD-Base: `mssql: [srv02, srv03]`, `mssql_link: [srv02]`
  - GOAD-Light-Base: `mssql: [srv02]`
- `install.yml`:
  - create `sql_svc` (password `Aa1234567890!`, no SPN) in north and, on GOAD-Base, essos;
  - run the `mssql` role on srv02 and srv03 (srv02 only on Light-Base) with sysadmins `NORTH\Administrator` / `ESSOS\Administrator`, as the Base config had;
  - run `mssql_ssms` on srv02.
- No vulnerable settings: no impersonation, no links, no low-priv sysadmins. Scenarios add those.

### `extensions/iis` (no VM)

- `extension.json`: `"machines": []`, `"compatibility": ["GOAD-Base", "GOAD-Light-Base"]`, `capabilities`: `iis: [srv02]` for both labs.
- `install.yml`: run the `iis` role on srv02.

### Code

- Extension metadata: read an optional `capabilities` map keyed by lab name from `extension.json`.
- Scenario resolver: effective capabilities = lab `capabilities` merged with the capabilities of the instance's installed extensions (union of host lists per key). Today `goad/labs.py` builds the resolver from the lab config only; it must take the instance's extension list into account.
- Extension install/remove and Vagrantfile/provider code: handle `machines: []` (no Vagrantfile fragment, no provider folders, no VM create/destroy).

### Removing an extension

`remove_extension` undoes what the install did:

1. Find the enabled scenarios that lose a capability they need: their `target` capability or a `requires` key would no longer cover them once the extension's capabilities are gone (capabilities the lab or another installed extension still grants keep them). Add their enabled dependents (scenario `depends`).
2. If that list is not empty, warn and list them by `name@target`, and ask: `Remove extension <name> and disable scenarios <keys>? (y/N)`. `--yes` answers yes. No TTY and no `--yes`: refuse.
3. On yes, disable those scenarios (scenario `uninstall.yml`), dependents first, with no per-scenario revert prompts. Any failure stops the removal; the extension stays installed.
4. Run the extension's `uninstall.yml`. It undoes the install:
   - `mssql`: uninstall SSMS and SQL Server, remove the MSSQL firewall rules, remove `sql_svc` from Log on as a service, delete the `sql_svc` domain users.
   - `iis`: remove the IIS feature (`Web-Server`) and its default content; reboot if Windows asks for it.
   Failure keeps the extension installed and reports the error.
5. Destroy the extension's VMs (none for `mssql`/`iis`), drop the extension from the instance, forget its snapshot.

The existing "revert to the pre-install snapshot" offer stays first; taking it skips the steps above. Extensions with VMs and no `uninstall.yml` keep today's behavior (destroy the VMs).

## Left to the builder

- Exact merge point for extension capabilities (resolver construction vs. lab object).
- How the SQL Server and SSMS uninstall commands are run (setup.exe `/ACTION=Uninstall` or package uninstall), as long as a later `install_extension mssql` works again.
- Test layout for the new extension metadata and resolver merge.
