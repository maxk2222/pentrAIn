# Defense notes — Agent Permission Boundaries

## Remediation

- Give each component a separate identity scoped to its function.
- Enforce row- and tenant-level authorization in the data service.
- Restrict the query service to approved views and read-only operations.
- Record the principal, source records, policy decision and action outcome.

## Verification

Use synthetic identities to test an approved summary query and denied
cross-business-unit and write requests. Confirm audit events allow reviewers
to reconstruct the source-to-action chain.
