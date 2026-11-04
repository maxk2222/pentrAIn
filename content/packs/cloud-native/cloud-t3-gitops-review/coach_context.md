# Coach context — Reconciliation Authority

## Intended path

1. Read `/opt/pentrain-audit/cloud/gitops-hardening-review.md`.
2. Compare reconciler scope and exception management with its production role.
3. Trace the deployment record to source revision and immutable artifact identity.
4. Write `/tmp/pentrain-audit-reports/reconciler-review.md` with evidence and verification.

## Common wrong turns

- Do not attempt to push a change or reconcile the supplied configuration.
- A signed image is not sufficient if the running digest is not linked to the approved source.
- Review permission scope and provenance as distinct controls.
