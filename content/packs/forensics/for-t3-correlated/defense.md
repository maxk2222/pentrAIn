# Defense notes — Correlated

## The kill chain (ground truth)

1. **edge01** (02:58–03:04): brute force → `Accepted password for webops`
   → stash in `/var/tmp/.s1` (scanner script + flag marker).
2. **app01** (03:07–03:12): ssh *from edge01's IP* as `appadm` →
   `/var/tmp/.s2` tooling (sshuttle-style port forwards visible in
   `.bash_history`).
3. **db01** (03:15–03:21): ssh *from app01* as `dbadm` → `/var/tmp/.s3`
   holds the staged `customer.sql.gz` + flag — then `rm`-style cleanup
   attempts in history.

`/var/log/collected.log` on db01 holds the forwarded syslog lines from all
three — sorted, it reads left-to-right as the full timeline.

## Detection lessons

- **Centralized logging is the difference**: without `collected.log` each
  host only shows a fragment; with it, the `from <prev-hop-ip>` chain is
  visible at a glance.
- **`.bash_history` on each hop** narrates the next hop — the fastest triage.
- **Staging dirs in /var/tmp/.s***: dotdirs + flag markers; tmpwatch/`/var/tmp`
  monitoring catches them.

## Fixes

- Central syslog/auditd shipping (as emulated by `collected.log`) with
  tamper-resistant storage off-box.
- Key-only ssh + per-host `AllowUsers`; alert on first-seen
  source→destination pairs.
- Lock down `/var/tmp` (`noexec`) and alert on dot-dirs created by services.

## Verify

- `grep Accepted /var/log/auth.log` on each host lists only expected admins.
- `find /var/tmp -name ".*"` shows no unknown dot-dirs.
