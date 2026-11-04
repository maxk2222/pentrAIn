# Defense notes — Exam: Helio Support

## Assessment themes

- Tenant authorization must be enforced by each retrieval and tool service.
- Retrieved ticket text is untrusted input, not policy.
- Tool actions require independent authorization and least-privilege identities.
- Audit records should connect source data, requesting principal and resulting action.

## Verification

Use synthetic users and records from separate business units. Confirm unauthorized
records are denied before summarization, tool calls are rejected without
authorization, and logs contain enough provenance to investigate a denied or
approved action.
