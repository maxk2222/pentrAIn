# Coach context — Permission Baseline

## Intended path

1. Read `/opt/pentrain-audit/linux/capability-review.md`.
2. Compare each listed capability with the allowed input/output directories.
3. Recommend removal or replacement with filesystem ownership and a minimal service identity.
4. Write `/tmp/pentrain-audit-reports/capability-review.md` with evidence and safe verification steps.

## Common wrong turns

- Do not attempt privilege escalation or interact with the local host beyond reading the fixture.
- Distinguish an inventory observation from proof that a service exercised the privilege.
- Include a negative test for access the service must not have.
