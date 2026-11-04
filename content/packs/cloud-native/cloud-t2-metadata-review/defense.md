# Defense notes — Metadata Boundary

## Remediation

- Deny access to metadata services from workloads that do not need them.
- Restrict outbound destinations and use a separate least-privilege identity per workload.
- Scope storage access to the required project and resource.
- Monitor metadata-network access and unexpected cross-project reads.

## Verification

Use synthetic identities and policy tests to confirm required access succeeds
while metadata and unrelated project access are denied.
