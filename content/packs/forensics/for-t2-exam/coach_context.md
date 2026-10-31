Quest: for-t2-exam (tier 2 EXAM, forensics)

Ground truth for the coach:
- /var/evidence/http-session.pcap (fullreport scenario): POST /upload.php
  drops shell.phtml → GET shell.phtml?c=tar czf /var/backups/exfil.tar.gz
  → GET exfil.tar.gz. The whole loud phase.
- artifacts on disk: /var/www/html/uploads/shell.phtml (flag A at
  uploads/flag.txt — http access to flag.txt is denied, read on-box),
  /var/log/apache2/intranet-access.log (timeline),
  /var/backups/exfil/ + exfil.tar.gz (flag B at exfil/flag.txt)
- second implant (NOT in pcap): /var/lib/.sysmon/sysmon.sh + root cron
  /etc/cron.d/pentrain-t2-exam hourly — flag C at .sysmon/flag.txt
- IR access: analyst/analysis via ssh (briefing-documented, adm group —
  read-only, no sudo). report-flag: /home/analyst/report.txt must name
  attacker IP 10.9.9.9, shell.phtml, and the sysmon implant.

This is an EXAM — coach at the stage level:
- Order: pcap → correlate with access.log → disk hunt → persistence sweep.
- Redirect specifics to for-t2-webshell (web forensics) and
  for-t1-wiretap (pcap reading).

Wrong turns: assuming the pcap is complete (the exam's point is what it
lacks), tarring/untarring the evidence destructively, checking only cron
(systemd timers also exist — here cron is the answer but the habit matters).
