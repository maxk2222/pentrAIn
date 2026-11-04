# Coach context — Model Provenance

## Intended path

1. Read `/opt/pentrain-audit/ai/model-registry-review.md`.
2. Identify the artifact trust evidence and what the worker can access.
3. Propose a safer artifact format and a provenance/approval check.
4. Write `/tmp/pentrain-audit-reports/model-provenance.md` with findings and verification.

## Common wrong turns

- Do not construct or load a model artifact.
- A filename alone does not identify or authenticate an artifact.
- Discuss isolation independently from artifact provenance.
