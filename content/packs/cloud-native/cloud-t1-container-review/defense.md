# Defense notes — Runtime Socket Exception

## Remediation

- Remove runtime control-socket access from workloads that only need metrics.
- Use a narrow read-only metrics endpoint or broker with an explicit schema.
- Avoid broad host filesystem mounts and document any necessary exception with an owner and expiry.

## Verification

Confirm the sidecar can read only its required synthetic health data and
cannot control containers or read unrelated host files.
