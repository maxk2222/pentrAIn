# Coach context — Runtime Socket Exception

## Intended path

1. Read `/opt/pentrain-audit/cloud/container-socket-review.md`.
2. Compare the monitoring requirement with the runtime socket and host mount.
3. Explain the authority boundary without interacting with a runtime.
4. Write `/tmp/pentrain-audit-reports/runtime-boundary.md` with a least-privilege alternative and verification.

## Common wrong turns

- Do not try a socket request or container operation.
- The finding is the unnecessary authority and mount, not proof of a container escape.
- Include both an allowed metrics check and denied control/file-access checks.
