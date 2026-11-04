# Defense notes — Reconciliation Authority

## Remediation

- Scope the reconciler identity to the namespaces and resource kinds it owns.
- Require protected, reviewed source changes and time-bound policy exceptions.
- Pin images by digest and verify signatures and provenance before deployment.
- Link each running artifact to its approved source revision and build record.

## Verification

Use a synthetic change to confirm out-of-scope resources are denied and
unreviewed artifacts are rejected. Verify exception ownership and expiry are
enforced.
