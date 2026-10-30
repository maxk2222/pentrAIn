Quest: linux-t2-exam (tier 2 EXAM, linux-fundamentals)

Ground truth for the coach:
- foothold: /etc/motd leaks maint / Maint2024! → ssh
- privesc A: sudo -l → NOPASSWD /usr/bin/journalctl → `sudo journalctl`
  then `!/bin/sh` in the pager
- privesc B: /etc/cron.d/pentrain-t2-exam — root runs
  `cd /home/maint/spool && tar czf ... *` every minute → plant
  --checkpoint=1 + --checkpoint-action=exec=sh /home/maint/pwn.sh
- flags: /home/maint/user.txt, /root/root.txt

This is an EXAM — coach at the stage level:
- If they got root via one path, *mention* there was a second and ask which
  they used — the exam rewards noticing both surfaces.
- Redirect to teaching quests: linux-t2-privesc-chain (sudo/GTFOBins),
  linux-t2-wildcard-cron (tar wildcard mechanics).

Wrong turns: editing the root cron line (root-owned; the DIR is writable),
forgot --checkpoint=1 (action never fires), sudo journalctl without a
pager trick (PAGER env / smaller window forces the pager).
