# Cheatsheet — The Whole Incident

## Targets

- **web02** — popped web server (pcap + access.log)
- **db02** — lateral target (auth.log + loot)
- IR access on both: `ssh analyst@` (pw `analysis`)

## Useful commands

```bash
# web02
tshark -r /var/evidence/http-session.pcap -Y http.request -T fields -e http.request.uri
grep -E 'upload|shell|c=' /var/log/apache2/access.log
grep -riE 'pass|host' /opt/shop/

# db02
grep -E 'Accepted|sudo' /var/log/auth.log
last -a; ls -la /var/backups/ /var/lib/mysql-exports/
find /var/backups -newermt '7 days ago'

# correlation trick — build the timeline side by side
grep -oE '[0-9]{2}/Nov/[0-9]{4}:[0-9:]+' /var/log/apache2/access.log | head
grep 'Nov 14' /var/log/auth.log
```

## Concepts

- Multi-host forensics: each host holds only its own truth — YOU merge it
- The last log line on host A is often the first log line on host B
- `sshpass` in a webshell command = the loudest lateral-move signature there is
