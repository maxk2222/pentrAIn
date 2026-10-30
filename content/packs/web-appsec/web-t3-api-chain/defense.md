# Defense notes — Broken Trust

## Vulnerability 1 — Server-Side Request Forgery (SSRF)

- **Weakness**: `/preview?url=` fetches an arbitrary URL server-side with no
  scheme, host, or IP-range allowlist.
- **Detect**: application logs show `/preview?url=http://internal-*` or
  loopback/link-local targets; egress logs on the container network show
  web→internal-api traffic that has no legitimate business reason.
- **Fix**: resolve and validate the target before fetching — allow only
  `https:`, reject private/loopback/link-local IPs **and** DNS names that
  resolve to them (re-check after redirects). Better: fetch via an egress
  proxy that can only reach the public internet.
- **Verify**: `curl 'http://app01/preview?url=http://internal-api:5000/'`
  must return an error, not API output.

## Vulnerability 2 — Internal API without authentication or isolation

- **Weakness**: `internal-api` serves `/admin/flag` to anyone who can reach
  the docker network; "internal" was the only access control.
- **Detect**: access logs on internal-api from the public-web container IP;
  absence of any auth header validation in the code.
- **Fix**: require a service token/mTLS on internal endpoints; put the API on
  a separate docker network the public app cannot join; apply
  `network_mode`/`internal: true` on the compose network.
- **Verify**: `docker exec public-web curl internal-api:5000/admin/flag`
  must fail with 401/403 or a connection error.
