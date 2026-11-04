# Defense notes — Exam: Production Boundary

## Assessment themes

- Workload identity should be unique, namespace-scoped and least-privileged.
- Untrusted source changes must not receive production secrets or deployment authority.
- Runners should be isolated and ephemeral.
- Deployments should use immutable artifact identities with verified provenance.

## Verification

Test required and denied authorization decisions with synthetic identities.
Exercise the fork-contribution path and confirm it cannot access secrets.
Verify that deployment rejects unreviewed or unverified artifacts.
