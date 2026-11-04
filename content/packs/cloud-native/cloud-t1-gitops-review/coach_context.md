# Coach context — Release Gate

## Intended path

1. Read `/opt/pentrain-audit/cloud/gitops-review.md`.
2. Trace which events start the test and publish jobs and what authority each receives.
3. Note worker persistence and how the published artifact is identified.
4. Write `/tmp/pentrain-audit-reports/gitops-review.md` with evidence, impact, control changes and verification.

## Common wrong turns

- Do not execute the workflow or try to obtain a token.
- A mutable tag is not a stable artifact identity.
- Treat runner isolation and secret scoping as separate controls.
