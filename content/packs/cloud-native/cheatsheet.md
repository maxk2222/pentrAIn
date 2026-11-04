# Cloud-native security review reference

## Kubernetes

- Review service accounts, Role/ClusterRole rules, bindings, namespaces and token mounts.
- Compare each permission to a documented workload requirement.
- Inspect manifests for privileged mode, host namespaces, host paths and unnecessary capabilities.

## Delivery and identity

- Separate untrusted contribution jobs from jobs that receive production credentials.
- Use isolated ephemeral runners and separate build and deploy identities.
- Pin immutable artifact digests and verify provenance before deployment.
- Test approved and denied access using synthetic identities; prefer read-only review.
