# Meridian model registry — artifact review

## Registry behavior

- Contributors can upload model artifacts to a shared validation queue.
- Validation workers load uploaded artifacts using a general-purpose object loader.
- The registry records a filename but does not verify a publisher signature or content digest.
- The worker has access to unrelated project configuration.

## Evidence

- Artifact `run-184` has no trusted publisher identity.
- The worker log records a load operation but no artifact digest.
- A model card includes a service credential in an example configuration.

## Required controls

Use non-executable data formats where practical, verify artifact provenance,
isolate validation workers and remove access to unrelated secrets.
