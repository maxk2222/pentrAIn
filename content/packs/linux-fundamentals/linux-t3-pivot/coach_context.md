Quest: linux-t3-pivot (tier 3, linux-fundamentals)

Ground truth:
- web01 (:21): nginx serves /var/www/html — index links to /docs/onboarding.txt
  which leaks `ssh student@web01 / Student2024!`. As student, the trainee
  reads /var/www/flag.txt (web flag) and /etc/intranet/config.ini which leaks
  `ssh_user=dbadm`, `ssh_pass=PivotOn24!`, `host=<db01 .22>`.
- db01 (:22): sshd accepts connections only from web01 (iptables). dbadm has
  NOPASSWD sudo → `sudo cat /root/db.txt`.
- flags: /var/www/flag.txt (web01, any local user can read),
  /root/db.txt (db01 — needs the pivot + sudo).

Intended path: enumerate web01 → /docs/onboarding.txt → ssh student@web01
→ read flag + config.ini → `ssh -J student@web01 dbadm@db01` (or -L/sshuttle)
→ `sudo cat /root/db.txt`.

Style: hardest of the linux track — guide the *concept* of pivoting, let them
choose the tool (ssh -J vs sshuttle vs manual hop). Praise good tradecraft.
