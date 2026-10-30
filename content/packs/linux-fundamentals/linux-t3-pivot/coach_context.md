Quest: linux-t3-pivot (tier 3, linux-fundamentals)

Ground truth:
- web01: /etc/intranet/config.ini contains `ssh_user=dbadm`, `ssh_pass=PivotOn24!`,
  `host=<db01>` (computed .22 of the same subnet)
- db01: sshd accepts connections only from web01 (iptables)
- flags: /var/www/flag.txt (web01), /root/db.txt (db01 — needs root on db01;
  dbadm can `sudo -l` — there's no sudo misconfig, so suggest
  `sudo -l` output checks + `find`/`cron` enumeration; the intended path is
  that dbadm is in the `sudo` group? Actually keep honest: dbadm is NOT sudo;
  intended = `sudo -l` shows nothing, then look for SUID/capabilities.
  Recommended hint: check `find / -perm -4000` or `getcap -r /` — but there's
  no extra misconfig on db01 besides `dbadm` being a shell user with sudo
  via password? Keep it simple: dbadm IS in sudo group (role sets append).
- intended path: recon web01 → read config.ini → ssh dbadm@db01 via -J or hop
  → sudo -l on db01 → root flag.

Style: hardest of the linux track — guide the *concept* of pivoting, let them
choose the tool (ssh -J vs sshuttle vs manual hop). Praise good tradecraft.
