# Defense notes — The Break-In

## What the attacker did

- **Brute force**: ~40 failed SSH passwords for `ops`, then an
  `Accepted password` — the credentials were weak (`ops/ops123`).
- **Stash**: dropped tools and the flag under `/tmp/.x11-cache/` — a
  dot-directory chosen to blend in.
- **Persistence**: a cron job `/etc/cron.d/sysupdate` running
  `/tmp/.x11-cache/upd` every 10 minutes (a dot-prefixed name would be
  skipped by cron — the attacker knew better).

## Detection lessons

- **Weak SSH credentials + exposed 22**: `auth.log` shows the brute-force
  burst pattern — dozens of `Failed password` then `Accepted`. Detect with
  fail2ban/SSHGuard or a SIEM rule on failure-rate.
- **Root-owned cron with a /tmp payload**: `ls -la /etc/cron.d/` + file
  timestamps correlate with the intrusion window. Integrity monitoring
  (AIDE/osquery) catches the new file.
- **Bash history left intact**: sloppy opsec — `HISTFILE` reading is the
  fastest triage after a compromise.

## Fixes

- Key-only SSH (`PasswordAuthentication no`), strong ops password, or
  disable the account.
- `noexec,nosuid,nodev` on `/tmp` blunts simple stash-and-run tradecraft.
- Cron allowlist + file-integrity alerts on `/etc/cron*`.

## Verify

- Re-check `auth.log` — no further `Accepted password` for ops.
- `crontab -l` and `/etc/cron.d/` contain only known jobs.
