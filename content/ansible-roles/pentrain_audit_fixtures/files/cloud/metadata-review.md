# Juniper cloud workload — identity and metadata review

## Architecture

- A document preview worker can make outbound requests to arbitrary destinations.
- The worker shares a cloud identity with the reporting service.
- That identity can read several storage projects, although the worker only needs one.
- The environment does not require metadata-service access from this workload.

## Synthetic incident record

Request record `CLOUD-41` shows a preview operation reaching a link-local
metadata network. The record contains no credential values. Storage audit
events show the worker identity reading an unrelated project.

## Expected controls

- Deny metadata access to workloads that do not require it.
- Restrict outbound destinations and cloud identity permissions.
- Use separate workload identities with short-lived, scoped credentials.
- Alert on unexpected metadata-network and cross-project access.
