# Defense notes — Release Gate

## Review goals

- Separate untrusted contribution checks from jobs with production secrets.
- Use ephemeral, isolated runners and prevent state from crossing job boundaries.
- Separate build and deployment identities.
- Pin artifacts by immutable digest and verify provenance and signatures before deployment.

## Verification

Simulate a fork contribution and confirm it receives no production credential.
Confirm the deploy stage accepts only a reviewed artifact with an approved
digest and provenance record.
