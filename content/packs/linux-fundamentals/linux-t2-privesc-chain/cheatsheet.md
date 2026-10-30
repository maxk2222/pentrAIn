# Cheatsheet — Privesc Chain

## Targets

- **app01** — several users, escalating rights; SUID + cron + sudo chain

## Useful commands

```bash
find / -perm -4000 -type f 2>/dev/null   # SUID hunting
sudo -l -l                               # per-user sudo rights
crontab -l; cat /etc/crontab; ls /etc/cron.*
getcap -r / 2>/dev/null                  # capabilities over SUID
```

## Concepts

- Chain logic: each hop's loot unlocks the next user
- Writable cron-run scripts = free root on the next cycle
- GTFOBins entries for `find`, `cp`, `tar`, `less` are the usual suspects
