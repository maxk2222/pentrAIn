# Defense notes — Privilege Chains

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Passwords in plaintext docs | `/etc/backup/restore-notes.txt` hands SSH creds to any reader | Secrets belong in a vault; docs reference the vault, never the secret |
| `NOPASSWD` sudo on `find` | `find . -exec /bin/sh \;` = instant root | Audit sudoers for GTFOBins binaries; least privilege only |
| World-writable root cron script | `/opt/maintenance/cleanup.sh` mode 777 → append reverse shell | Root-owned scripts must be `0750`/`0755` in root-owned dirs; audit cron targets |
| Reused/weak password | `Summer2024!` is pattern-guessable | Password manager + rotation; disable password SSH |

## Audit commands

```bash
# sudoers hygiene
grep -R 'NOPASSWD\|/usr/bin/find\|vim\|nmap\|less\|more' /etc/sudoers /etc/sudoers.d/

# cron targets writable by non-root
for f in $(crontab -l -u root 2>/dev/null | grep -oP '/[^ ]+\.(sh|py)'; find /etc/cron* -type f); do
  [ -w "$f" ] && echo "WRITABLE cron target: $f"
done

# plaintext secret sweep
grep -rIlnE 'passw|secret|token' /etc /opt /srv --include='*.txt' --include='*.ini' 2>/dev/null
```

## Detection

- auditd rule on `/etc/sudoers.d` writes and on executions of `find`/`vim` via sudo
- cron script integrity monitoring (inotifywait / AIDE) on `/opt/maintenance`
- alert on `sh`/`bash` spawned by `find`, `vim`, `less`, etc.

## Further reading

- GTFOBins: https://gtfobins.github.io/
- payloadbox writable-cron privesc notes
