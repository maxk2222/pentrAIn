# Defense notes — Model Provenance

## Control requirements

- Prefer non-executable, schema-validated artifact formats.
- Record trusted publisher identity, immutable digest and approval status.
- Validate artifacts in a disposable worker with no unrelated credentials or network access.
- Keep a provenance record from training source through validation and deployment.

## Verification

Confirm an unsigned or unrecognized synthetic artifact is rejected before
loading. Verify worker access is limited to the review job and that the
approved digest matches the promoted artifact.
