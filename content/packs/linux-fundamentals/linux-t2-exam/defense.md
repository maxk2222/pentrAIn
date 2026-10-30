# Defense notes — The Maintenance Window

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Credentials in /etc/motd | Banner = free shell | Motd is for notices, never secrets |
| `sudo journalctl` NOPASSWD | Pager → `!sh` → root | Drop the sudoers scope; ship logs via journald-remote or a collector |
| root `tar *` on user dir | Filenames → root command execution | Absolute path archive, or run the job as the dir owner |
| Same cron cadence, same bug class | 60s exploit loop | Fix the wildcard; cadence isn't the bug |

## Audit commands

```bash
grep -rn NOPASSWD /etc/sudoers /etc/sudoers.d/
grep -RInE '\*' /etc/crontab /etc/cron.d/          # wildcards in privileged jobs
find /home -name '-*' 2>/dev/null                 # planted argument-files
cat /etc/motd | grep -iE 'pass|cred'              # banner secrets
```

## Detection

- auth.log: sudo invocations of journalctl ending in a shell spawn
- auditd execve on tar (euid 0) in user-writable dirs
- new files matching `^-` under cron-archived directories

## Further reading

- GTFOBins journalctl / tar
- pager escape: LESS, PAGER env vars and why scoped pagers aren't safe
