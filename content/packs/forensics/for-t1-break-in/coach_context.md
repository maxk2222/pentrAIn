# Coach context — The Break-In

## Intended path

1. `ssh analyst@<evidence01>` (pw `analysis`) — read-only triage.
2. `sudo grep -E "Failed|Accepted" /var/log/auth.log` → brute-force burst
   (~40 `Failed password for ops`), then `Accepted password for ops` at the
   top of the window. Source IP is bogus `10.66.6.6` — it was tunneled.
3. `sudo cat /root/.bash_history` (attacker escalated) or
   `cat /home/ops/.bash_history` → commands show them mkdir'ing
   `/tmp/.x11-cache`, dropping `upd`, writing the cron.
4. `sudo ls -la /tmp/.x11-cache/` → `flag.txt` → **stash-flag**.
5. `sudo ls -la /etc/cron.d/` → `sysupdate` (a valid job — cron skips
   dot-names) → the flag file sits hidden beside it:
   `/etc/cron.d/.sysupdate-flag` → **persistence-flag**.

## Key facts (stage 2–3 only)

- Compromised account: `ops` (password `ops123`).
- Analyst credentials are in the briefing — trainees who don't read it stall
  on the login prompt; remind them early.
- The two flags are at `/tmp/.x11-cache/flag.txt` and
  `/etc/cron.d/.sysupdate-flag`; sudo covers every artifact uniformly
  (analyst is NOPASSWD — encourage it if a trainee hits permission walls).

## Common wrong turns

- Attacking the box (nmap/hydra) — it's a forensics quest, the evidence is
  inside.
- `cat auth.log` without sudo → permission denied; analyst has NOPASSWD sudo.
- Looking only in /var/log — the richest trail is `.bash_history`.
