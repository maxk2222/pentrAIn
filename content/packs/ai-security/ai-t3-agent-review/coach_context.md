# Coach context — Agent Permission Boundaries

## Intended path

1. Read `/opt/pentrain-audit/ai/agent-boundary-review.md`.
2. Map the planner, query service and report writer to their identities and data access.
3. Compare each access path with the documented analyst scope.
4. Write `/tmp/pentrain-audit-reports/agent-boundaries.md` with evidence, risk, remediation and verification.

## Common wrong turns

- Do not try to interact with an agent or database; this is static evidence.
- A user-interface check is not a data-service authorization boundary.
- Include what the audit log must capture, not just that logging should be enabled.
