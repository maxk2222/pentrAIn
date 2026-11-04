# Defense notes — The Retrieval Boundary

## Findings to validate

- Authorization after retrieval is too late if unfiltered chunks are already sent to a summarizer.
- A shared agent identity and overly broad tools expand the impact of prompt or data-boundary failures.
- Retrieved text must not be treated as trusted policy or as authorization to call a tool.

## Detection and remediation

- Log the tenant, principal and document identifiers at the data-access boundary.
- Apply tenant and role filters in the retrieval query and re-check authorization in each tool.
- Separate policy from retrieved content; preserve a source-to-action audit trail.
- Test cross-tenant access with synthetic records and verify denied records never reach downstream model components.
