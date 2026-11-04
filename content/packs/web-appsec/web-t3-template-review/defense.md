# Defense notes — Template Trust

## Remediation

- Select a fixed, server-owned template by an allowlisted identifier.
- Pass customer values as data; do not interpret customer-supplied text as template source.
- Keep template rendering least-privileged and avoid exposing sensitive application objects.

## Verification

Use a harmless literal string as customer data and confirm it is rendered as
data. Confirm only approved layout identifiers are accepted and unknown ones
are rejected without evaluation.
