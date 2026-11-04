# Defense notes — Permission Baseline

## Remediation

- Remove capabilities not required by the service's documented function.
- Prefer a dedicated unprivileged service identity and narrow filesystem ownership.
- Keep an approved capability baseline and alert on changes.

## Verification

Confirm the service still completes its intended task after the change.
Use a separate synthetic identity to verify unrelated files and administrative
operations remain denied.
