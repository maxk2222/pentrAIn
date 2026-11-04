# Defense notes — NeuralSwarm

## Review dimensions

- Keep retrieved AI content separate from policy and enforce authorization at each tool boundary.
- Scope workload identities and separate build permissions from deployment authority.
- Protect untrusted contribution workflows from secrets and persistent runner state.
- Verify release provenance and remove unnecessary host privileges.

## Incident-response output

The final report should connect evidence across components without assuming
that one issue proves another. Prioritize immediate exposure reduction, name
the permanent control changes and define a safe verification step for each.
