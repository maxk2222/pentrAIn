# Coach context — scr-t1-bash-recon

## Intended solve
- Target `filesrv01` (10.x.10.20): sshd :22, nginx on **:8080** (deliberately
  non-standard), vsftpd anonymous on :21 serving /srv/ftp/users.csv.
- `/var/log/auth.log` is a planted corpus: failed logins from 203.0.113.66
  (the brute-forcer, 5 attempts) and 198.51.100.23 (2 attempts), benign
  logins from 10.x.10.5.
- Flag 1 (command, checked on kali): `/root/recon.sh` executable, and running
  it prints something containing `8080` — i.e. the script must actually find
  the web port, not just exist. **The check calls it with no args** — the
  script needs the target baked in (`filesrv01` resolves inside the range,
  or the 10.x.10.20 octet convention).
- Flag 2 (command, kali): `/root/attackers.txt` contains `203.0.113.66`.

## Reference script shape (don't hand out verbatim)
```bash
#!/bin/bash
T=${1:-filesrv01}        # no arg → default target
for p in 21 22 80 443 8080 3306; do
  (echo > /dev/tcp/$T/$p) 2>/dev/null && echo "$p open"
done
```
or `nmap -p- -T4 $T`. For the log: `scp trainee@…` (trainee/Start123! also
exists as a login), or `ssh` remote cat, or `curl ftp://$T/users.csv`.
Then `grep 'Failed password' auth.log | awk '{print $11}' | sort | uniq -c
| sort -rn | head -1 | awk '{print $2}' > /root/attackers.txt`.

## Coach guidance
- Watch for: writing recon.sh in the wrong place (must be /root), forgetting
  +x, scripts that hardcode "8080" into output (accept — output is what's
  graded, but gently note the point is real probing).
- Attackers.txt pitfalls: grabbing "Accepted password" IPs, missing the
  sort|uniq -c ranking step, writing the count instead of the IP.
- Escalate slowly — this is a fundamentals quest; let them iterate.
