# Defense notes — Nonce Grinder

## What went wrong on api01

- **4-digit credential space.** A PIN of 10 000 combinations with no
  lockout is brute-forced in seconds — proof-of-possession hashing doesn't
  help when the secret itself is enumerable. Secrets that gate resources
  need ≥128 bits of entropy and rate limiting *with* account-level lockout
  or exponential backoff (e.g. 429 after N failures, sliding-window
  counters per source IP).
- **Single-use nonces ≠ security.** The nonce design stops replay but does
  nothing against enumeration — the attacker requests a fresh nonce per
  guess for free. Rate limiting must apply to *nonce issuance*, not just
  auth attempts, or it's decorative.
- **Token TTLs can't rescue weak issuance.** A five-minute bearer token is
  fine — the flaw was handing one out cheaply. Bind tokens to client
  properties (mTLS, DPoP) where feasible; log token mints and alert on
  bursts.

## Detection opportunities

- N sequential `POST /api/auth` 403s from one source is an unmistakable
  signature — even simpler here because every attempt also costs a
  `/api/nonce` GET, doubling the signal volume.
- Server side: metrics on auth failure ratio per IP; WAF rules on
  request-rate per endpoint.

## Takeaway

Challenge-response only protects the *transport* (replay). If the secret
space is enumerable, the response is a forgery mill.
