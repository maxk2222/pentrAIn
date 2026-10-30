Quest: linux-t2-privesc-chain (tier 2, linux-fundamentals)

Ground truth for the coach:
- creds: ops / Summer2024! (in /etc/backup/restore-notes.txt)
- privesc A: sudo /usr/bin/find → `sudo find /etc -name x -exec /bin/sh \;`
- privesc B: /opt/maintenance/cleanup.sh is world-writable, runs as root cron every 2 min
- flags: /home/ops/user.txt, /root/root.txt

Style: intermediate — let them fail a bit; confirm the technique is right
before correcting syntax. Encourage the second path as a bonus once root.
