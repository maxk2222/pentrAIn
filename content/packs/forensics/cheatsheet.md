# Forensics — reference card

## Triage order

```bash
# 1. timeline — what happened when
find / -newermt "2024-03-14" ! -newermt "2024-03-16" -type f 2>/dev/null
# 2. auth events
grep -E "Failed|Accepted|Invalid" /var/log/auth.log
journalctl -u ssh --since "2024-03-14"
# 3. user artifacts
cat /home/*/.bash_history; ls -la /home/*/ /root/
# 4. persistence
ls -la /etc/cron* /var/spool/cron; systemctl list-units --type=service
```

## Reading logs fast

```bash
grep "Failed password" auth.log | awk '{print $11, $9}' | sort | uniq -c | sort -rn
# lastlog / wtmp / btmp — who logged in, from where
last -f /var/log/wtmp | head; lastb -f /var/log/btmp | head
```

## Common artifact homes

- `/tmp`, `/var/tmp`, `/dev/shm` — attacker scratch space (hidden dot-dirs!)
- `/var/www/html/uploads/` — webshell country
- `~/.ssh/authorized_keys` — backdoor keys
- bash_history of *any* user — attackers forget to clean
- `~/.mysql_history`, editor swap files `.*.swp`

## Correlation

- Normalize timestamps across hosts — same attacker, same minute
- `sort -m` merged logs; grep the attacker IP everywhere
- webshell calls leave `GET/POST <shell>?c=` lines in access.log

## Worth remembering

- cron.d filenames containing a dot are skipped by cron — `.foo` = inert
- `stat` gives birth/modify/change times — compare against log claims
- A file's `atime` after `find` doesn't lie — but `touch -r` can fake mtime
