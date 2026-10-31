# Cheatsheet — The Maintenance Window

## Targets

- **maint01** — ssh + a pre-auth banner + two escalation paths

## Useful commands

```bash
ssh <user>@<ip>                   # the ssh Banner shows BEFORE login
cat /etc/motd /etc/issue.net      # where contractors' accounts get posted
sudo -l
crontab -l; cat /etc/crontab; ls /etc/cron.d/
find / -writable -type f 2>/dev/null | grep -v '^/home'
```

## Concepts

- Scoped sudo is still root — the question is only which binary (GTFOBins)
- Root jobs over user-writable dirs: the dir is the attack surface
- Always check BOTH: `sudo -l` AND the cron tables
