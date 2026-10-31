# Coach context — scr-t1-exam

## Ground truth
- `audit01` 10.x.10.20: sshd :22, nginx :8080 (`/status.json` =
  `{"host":"audit01","uptime_h":412,"services":["sshd","nginx","vsftpd"],
  "backup":"daily"}`), vsftpd anonymous → `/srv/ftp/assets.csv`
  (audit01, ws-edge, mailrelay, vault).
- auth.log: **203.0.113.44 is clearly dominant** (5 failures) vs
  192.0.2.99 (3) — a straight `sort|uniq -c|sort -rn|head -1` lands the
  graded value `ATTACKER=203.0.113.44`.
- Flags (command, kali): `/root/report.sh` executable + runs; and
  `/root/report.txt` matches `SERVICES=.*nginx`, `ATTACKER=203.0.113.44`,
  `ASSETS=.*vault`.

## Expected script shape
```bash
#!/bin/bash
T=10.x.10.20
ssh/cat auth.log → top attacker IP
curl -s ftp://$T/assets.csv | tail -n+2 | cut -d, -f1 | paste -sd,
curl -s http://$T:8080/status.json | tr -d '{}"' | parse services
printf 'SERVICES=%s\nATTACKER=%s\nASSETS=%s\n' ... > /root/report.txt
```

## Coach guidance
- Exams: hold back more than teaching quests. Nudge on approach ("three
  sources, three pipelines"), not on values.
- Watch: JSON parsing with grep/sed is fine at this tier — don't push jq.
