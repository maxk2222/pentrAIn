# Defense notes — Protocol Ownership

## Control requirements

- Maintain an owner, version and approval record for each tool.
- Give each tool only the data and operations required for its use case.
- Re-authorize each action in the tool service; model context is not authorization.
- Treat tool descriptions and results as untrusted input.
- Record the user, tool version, data source and decision for every consequential action.

## Verification

Test an approved read-only action and a denied cross-scope action using
synthetic identities. Confirm a tool change cannot reach production without
review and an attributable record.
