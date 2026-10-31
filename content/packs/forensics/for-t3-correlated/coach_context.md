# Coach context — Correlated

## Intended path

1. `ssh analyst@<edge01>` (pw `analysis`, sudo) →
   `sudo grep Accepted /var/log/auth.log` → `webops` fell at 02:58.
   `/var/tmp/.s1/flag.txt` → **entry-flag**.
2. webops' `.bash_history` on edge01 → `ssh appadm@app01`.
   On app01: `sudo grep Accepted /var/log/auth.log` → source = edge01's IP.
   `/var/tmp/.s2/flag.txt` → **pivot-flag**.
3. appadm's `.bash_history` → `ssh dbadm@db01`. On db01: same pattern →
   `/var/tmp/.s3/flag.txt` → **exfil-flag** (beside `customer.sql.gz`).
4. Timeline correlation: `sort /var/log/collected.log` on db01 — forwarded
   syslog from all three hosts proves the chain end-to-end.

## Key facts (stage 2–3 only)

- Compromised accounts in order: `webops` (edge01) → `appadm` (app01) →
  `dbadm` (db01). All used weak stored passwords.
- Staging dirs: `/var/tmp/.s1`, `.s2`, `.s3` — flag file inside each.
- `/var/log/collected.log` on db01 is the "aha" — lines prefixed with the
  source hostname; sorting by time reconstructs the kill chain.
- report-flag: /home/analyst/report.txt **on db01** must name all three
  abused accounts: webops, appadm, dbadm.
- `analyst/analysis` creds are in the briefing on every host.

## Common wrong turns

- Analyzing all three hosts separately without ordering — the `from` IPs in
  auth.log are the chain; collected.log is the shortcut.
- Treating the bogus attacker source `10.66.6.6` as meaningful — it tunneled;
  the *internal* hops are what matter.
- Missing that db01 was the exfil point — `customer.sql.gz` in `.s3` is the
  payload, `flag.txt` beside it is the objective.
