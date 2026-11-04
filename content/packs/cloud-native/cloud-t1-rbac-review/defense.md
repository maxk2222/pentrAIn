# Defense notes — The Overbroad Role

## Review goals

- Replace wildcard resources with only the required resource names.
- Reduce verbs to the minimum actions required; avoid write and delete permissions where reads suffice.
- Keep roles namespace-scoped and use separate identities for distinct workloads.

## Detection and verification

- Review Role and RoleBinding changes in source control.
- Compare observed authorization decisions with the approved workload matrix.
- Test both the required read operation and representative denied operations.
- Alert on unexpected role changes and service-account token use.
