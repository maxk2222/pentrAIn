# Defense notes — Wildcard

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `tar czf … *` in a root cronjob | Filenames in a user-writable dir become root-privileged arguments | Quote paths absolutely: `tar czf out.tgz /home/ops/backup` or `cd dir && tar czf out.tgz -- *`; better: `find -print0 \| tar --null -T -` |
| Archiving a user-writable dir as root | Attackers fully control the argument surface | Run the job as the directory's owner, not root |
| Plaintext creds in `/var/backups` | Free SSH | Secrets in a vault |
| Cron cadence too generous | A 60s exploit window forever | Fix the vuln; don't rely on slower schedules |

## Audit commands

```bash
# wildcard use in privileged jobs — the whole class of bug
grep -RInE '(\*|\.sh)' /etc/crontab /etc/cron.d/ /var/spool/cron/crontabs/
grep -RInE '\btar\b|\bcp\b|\brsync\b.*\*' /etc/cron* 2>/dev/null

# files whose names start with a dash — someone's been here (or will be)
find /home /tmp /var -name '-*' 2>/dev/null

# plaintext secret sweep
grep -rIlnE 'passw|cred' /var/backups /etc /opt 2>/dev/null
```

## Detection

- auditd execve rules for `tar` running with euid 0
- alert on filenames matching `^--` in cron-touched dirs
- FIM on `/etc/cron*` and on files new files in archived dirs

## Further reading

- GTFOBins "tar" — wildcard/checkpoint technique
- Defense in depth: `--` end-of-options and why scripts should always emit it
