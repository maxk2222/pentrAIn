# Defense notes — Three Hops Deep

## The chain

- `dmz01` leaks `ops/ops123` in an HTML comment → SSH foothold.
- `ops@dmz01` home holds `notes.txt` with `appadm` credentials for `app01`.
- `appadm@app01` home holds `db-notes.txt` with `dataadm` credentials.
- `dataadm@data01` has NOPASSWD sudo → `/root/flag.txt`.

## Vulnerabilities

- **Credentials in comments/notes**: HTML comment on dmz01, plaintext
  `notes.txt`/`db-notes.txt` in user homes — the classic "ops runbook as
  password manager" anti-pattern.
- **Source-IP trust as the only segmentation control**: host firewalls
  accept anything from the previous hop — one foothold inherits the whole
  trust chain.
- **NOPASSWD sudo on the deepest host**: `dataadm` owns data01 with zero
  friction.

## Detection

- `auth.log` chains: an `Accepted` on each host shortly after the previous
  hop's session — correlate across hosts (central syslog would make the
  lateral path obvious).
- New ssh source = previous tier's IP at odd hours; `sshuttle`/proxy traffic
  shows as long-lived sessions.

## Fixes

- Remove credentials from files/pages entirely; vault + short-lived access.
- Port-scoped firewall rules (only the service ports the tier actually
  needs), and per-service auth — not blanket host trust.
- Drop NOPASSWD sudo; require pam auth or signed sudo tokens.

## Verify

- `grep -r "pass" /var/www/html` → nothing.
- `sudo -l` as dataadm requires a password; passwords rotated.
