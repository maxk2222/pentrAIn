# Atlas production reconciler — policy review

## Reconciler configuration

- The reconciler identity can modify resources in every namespace.
- Production accepts images by mutable tag; no digest is recorded in the release record.
- Source branch protection is optional for repositories connected to production.
- A policy exception has no owner or expiry date.

## Release evidence

Deployment `REL-208` has no signature-verification result. The deployment
record does not link the running image to a reviewed source revision.

## Expected controls

Scope reconciliation permissions, require reviewed protected changes, pin
immutable artifacts, verify provenance and expire policy exceptions.
