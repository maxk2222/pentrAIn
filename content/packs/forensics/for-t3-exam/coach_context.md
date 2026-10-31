Quest: for-t3-exam (tier 3 EXAM, forensics)

Ground truth for the coach:
- web02 (.58): /var/evidence/http-session.pcap (wholeincident scenario) +
  access.log — POST /upload.php drops shell.phtml; commands escalate:
  id → /etc/hosts → grep db → sshpass ssh dbmaint@db02. /opt/shop/db.ini
  leaks dbmaint creds. Flag A: /var/www/html/uploads/flag.txt
  (http access to flag.txt denied — read on-box)
- db02 (.59): /var/log/auth.log — Accepted password for dbmaint from
  web02's IP, sudo tar czf /var/backups/loot.tar.gz /var/lib/mysql-exports.
  Flag B: /var/backups/loot/flag.txt. Flag C: /home/dbmaint/flag.txt —
  dbmaint's home is 0700: requires ssh dbmaint@db02 with DbMaint2024!.
- IR access: analyst/analysis on both (adm group, read-only — no sudo).
  report-flag: /home/analyst/report.txt on db02 must name dbmaint +
  loot/mysql-exports.

This is an EXAM — coach at the stage level:
- The exam's core is CORRELATION: ask them to narrate the timeline
  (upload → shell → db discovery → lateral ssh → staging) before pushing
  to the next flag.
- Redirect to for-t2-webshell (log forensics) and for-t1-wiretap (pcap).

Wrong turns: stopping at web02 (the exam is the second host), assuming
the webshell was the only access (the dbmaint ssh session is separate),
missing that /opt/shop/db.ini explains HOW they learned db creds.
