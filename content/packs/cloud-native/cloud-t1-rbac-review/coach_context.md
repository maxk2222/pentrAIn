# Coach context — The Overbroad Role

## Intended path

1. Read `/opt/pentrain-audit/cloud/rbac-review.md`.
2. Compare the role's API groups, resources and verbs with the stated need.
3. Consider whether the public catalogue and scheduled import job need separate identities.
4. Write `/tmp/pentrain-audit-reports/rbac-review.md` with evidence, risk, reduced-permission changes and verification.

## Common wrong turns

- Do not deploy the sample manifest.
- Avoid generic advice; identify which categories of permission are excessive for each workload.
- Include a positive and negative authorization check in the verification plan.
