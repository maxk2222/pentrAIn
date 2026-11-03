# Defense notes — Split-Second

## Vulnerability 1 — HTTP request smuggling (0.CL desync)

- **Weakness**: the edge proxy parses the request head once, then forwards
  the raw byte stream; a `Content-Length: 0` request with an appended body
  becomes a whole second request on the backend connection — invisible to
  every edge control (ACL, logging, WAF).
- **Detect**: backend access logs containing requests the edge log never
  recorded (compare per-connection request counts); anomalies like a
  backend `POST /internal/report` with no matching edge entry.
- **Fix**: reject ambiguous requests at the edge — normalize/verify
  `Content-Length`, drop connections carrying unexpected bytes instead of
  piping blindly; front HTTP/2 end-to-end or to the backend (fixed framing
  removes ambiguity); use a mature proxy that parses every request on the
  wire.
- **Verify**: send the lab payload — backend log must contain ONLY
  `POST /track`; a second response must never arrive.

## Vulnerability 2 — internal endpoints protected by the perimeter only

- **Weakness**: `/internal/flag` and `/internal/report` have no auth of
  their own; the edge ACL was the single control — a bypass means total
  exposure.
- **Detect**: internal API serves privileged responses to unauthenticated
  requests arriving on backend connections.
- **Fix**: defense in depth — require authn on internal endpoints too
  (service token/mTLS); mark trusted hops (`X-Forwarded-By`) and have the
  backend reject requests without it.
- **Verify**: `docker exec edge curl backend:5000/internal/flag` must be
  rejected even though it bypasses the public edge entirely.
