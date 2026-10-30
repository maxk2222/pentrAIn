Quest: net-t2-dns-enum (tier 2, network-recon)

Ground truth for the coach:
- bind9 serves zone corp.local; allow-transfer {any;} → `dig @ip corp.local axfr`
  returns ns1/admin/backup/tftp/intranet/files (all → the same box)
- snmpd: rocommunity public, full tree — sysContact = backup-op@corp.local,
  extend 'backup-memo' prints "nightly sync runs as backup-op — password is
  the weak corp standard"
- tftpd-hpa serves /srv/tftp unauthenticated — flag.txt lives there
- flag A: /srv/tftp/flag.txt — `tftp <ip> -c get flag.txt` (or `atftp`)
- flag B: /home/backup-op/user.txt — hydra ssh backup-op with a common
  wordlist; password is `backup123` (in rockyou + metasploit unix_passwords)
- sshd password auth on

Intended path:
nmap -sU → dig axfr → tftp get flag → snmpwalk → username → hydra → ssh

Common wrong turns:
- TCP-only nmap — DNS/TFTP/SNMP are UDP; nudge `-sU --top-ports`
- using rockyou.txt.gz compressed — hydra can't read gz; either gunzip or
  use /usr/share/wordlists/metasploit/unix_passwords.txt
- trying to brute-force DNS names instead of just asking (axfr IS the point)

Style: tier 2 — protocol breadth is the lesson (4 different services, each a
different tool). Keep them moving between tools, not deeper into one.
