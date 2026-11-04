---
id: cloud-security-audit
title: Cloud-native security — identity, metadata and deployment policy review
triggers: [kubernetes, serviceaccount, rbac, metadata, imds, docker.sock, gitops]
---

## Audit workflow

1. Map workload identities to namespaces, roles and the exact resources and verbs they need.
2. Inspect manifests and runtime configuration for privileged mode, host namespaces, host paths and mounted control sockets.
3. Review cloud metadata access policy and whether workloads can obtain credentials they do not need.
4. Trace deployment changes from source repository through CI identity to the cluster reconciler.
5. Check that secrets are not exposed through manifests, logs, image layers or build artifacts.
6. Use read-only inventory and authorization checks first; save evidence in a local report.

## Remediation checks

- Apply least-privilege RBAC and disable unnecessary service-account token mounts.
- Deny privileged workloads and host mounts by default; scope exceptions narrowly.
- Require reviewed, signed artifacts and protected deployment branches.
- Keep credentials short-lived, audience-bound and unavailable to unrelated workloads.
