# Defense notes — Recon.sh

## What went wrong on filesrv01

- **Anonymous FTP exposure.** A world-readable share with the host inventory
  hands attackers free recon: usernames, owners, team names for social
  engineering. Disable `anonymous_enable`, or at minimum drop anonymous write
  *and* read; require authenticated access (SFTP or authenticated FTP).
- **Noisy, unwatched auth.log.** Five+ failed logins from a single external
  IP inside minutes is a textbook brute-force signature — and nothing acted
  on it. `fail2ban` or sshd's `MaxAuthTries` + a `DenyUsers` policy would
  have stalled this; forwarding auth logs to a SIEM with a threshold alert
  (e.g. >3 failures/source/5min) makes it visible.
- **Service sprawl.** nginx on 8080 was "temporary" — undocumented listeners
  are exactly what port scans find first. Keep a service inventory; close
  anything not needed (`systemctl disable --now`), or bind internal
  services to localhost/a management interface and firewall the rest.

## Detection opportunities

Outbound scanning is noisy: a burst of SYN connects across many ports from
one source is trivially detectable (netflow, `ss`/`conntrack` thresholds,
Suricata ET SCAN rules). Failed-password spikes appear in auth.log before
any success — alerting on volume per source IP catches both.

## Takeaway for trainees

Every line your script writes is also a detection opportunity for the blue
team. Automation doesn't just save *you* time — it standardizes evidence an
audit can replay.
