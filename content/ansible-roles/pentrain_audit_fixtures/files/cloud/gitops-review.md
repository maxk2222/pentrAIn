# Atlas deployment pipeline — review bundle

## Pipeline policy

- Pull requests from forks use the same runner pool as protected-branch builds.
- The runner identity can update production workloads and read all project secrets.
- Image deployment uses the mutable tag `latest`.
- Production reconciliation accepts unsigned images from the shared registry.

## Expected control outcomes

- Untrusted changes must not receive production credentials.
- Build and deploy identities must be separate and narrowly scoped.
- Deploy an immutable, verified artifact reference.
- Require review and record provenance before production reconciliation.
