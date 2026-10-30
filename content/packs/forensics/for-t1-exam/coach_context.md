Quest: for-t1-exam (tier 1 EXAM, forensics)

Ground truth for the coach:
- /var/evidence/evidence.pcap (blackbox scenario): FTP session leaks
  nightops / NightShift9! + memo naming /var/lib/.fonts-cache/persist.sh
  and fonts-cache.service; "same password works for ssh"
- ssh nightops@ → /home/nightops/user.txt (user flag)
- .bash_history → /var/tmp/.apt-cache/ (stash flag at flag.txt)
- /var/lib/.fonts-cache/ + /etc/systemd/system/fonts-cache.service →
  persistence flag at flag.txt inside the cache dir

This is an EXAM — coach at the stage level:
- Order matters: capture → creds → shell → history trail → persistence.
  If they ssh first without reading the pcap, that's fine mechanically but
  ask what the capture gave them — the exam tests derivation, not luck.
- Redirect to teaching quests (for-t1-break-in for trail-reading,
  for-t1-wiretap for capture work) rather than giving answers.

Wrong turns: hunting for a second protocol in the pcap (it's all ftp),
checking crontab only (persistence here is a systemd unit), deleting
evidence files instead of reading them.
