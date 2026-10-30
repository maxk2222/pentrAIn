# Defense notes — Behind the Firewall

## Vulnerability 1 — Credentials in the web root

- **Weakness**: `/var/www/html/config.php` contains plaintext credentials
  for `deploy@edge01` and `internal_svc@internal01` — readable over HTTP.
- **Detect**: access.log shows `GET /config.php` from the range IP; the file
  shouldn't be under the docroot at all.
- **Fix**: move credentials to environment secrets outside the docroot;
  deny `*.php` source serving or never put cred files there; rotate both
  accounts.
- **Verify**: `curl http://edge01/config.php` returns 404; both accounts
  refuse the old passwords.

## Vulnerability 2 — Weak static passwords on both accounts

- **Weakness**: `deploy/deploy123`, `internal_svc/L3tM3In!` — guessable and
  stored where any web visitor finds them.
- **Detect**: `auth.log` Accepted entries for both users from unexpected
  source IPs (edge01's own address for internal01 is expected — the anomaly
  is a *first-time* source).
- **Fix**: key-only SSH, strong rotated passwords, `AllowUsers` lists.
- **Verify**: `ssh -o PreferredAuthentications=password` fails.

## Vulnerability 3 — Flat trust zone (single allow rule)

- **Weakness**: internal01 trusts *everything* from edge01's IP — one
  compromised host = full access.
- **Detect**: nftables counters show accepts from edge01 on ports it never
  legitimately uses.
- **Fix**: least-privilege allow rules (specific ports only), an actual
  router/firewall between segments, mTLS or signed access — not source-IP
  trust.
- **Verify**: from edge01, only the intended service ports on internal01
  answer.
