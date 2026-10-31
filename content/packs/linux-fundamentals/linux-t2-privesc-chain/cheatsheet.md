# Cheatsheet — Privesc Chain

## Targets

- **server01** — backup host; anonymous share, sudo rights, writable cron script

## Useful commands

```bash
nmap -sV -sC <server01>
ftp anonymous@<server01>             # anonymous read shares leak procedures
find / -perm -4000 -type f 2>/dev/null   # SUID hunting
sudo -l                                # per-user sudo rights
crontab -l; cat /etc/crontab; ls /etc/cron.*
getcap -r / 2>/dev/null                  # capabilities over SUID
```

## Concepts

- Chain logic: each hop's loot unlocks the next user
- Writable cron-run scripts = free root on the next cycle
- GTFOBins entries for `find`, `cp`, `tar`, `less` are the usual suspects
