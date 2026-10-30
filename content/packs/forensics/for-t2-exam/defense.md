# Defense notes — Full Report

## What went wrong (the attacker's side)

| Issue | Evidence | Fix |
|---|---|---|
| Upload executed arbitrary PHP | shell.phtml in uploads/ + pcap POST | Allowlist extensions; `php_admin_flag engine off` on upload dir; store outside docroot |
| Webshell → host commands | `?c=tar czf …` in capture + log | mod_security OWASP CRS; disable system()/exec() for www-data via php.ini disable_functions |
| exfil staged in /var/backups | exfil/ + exfil.tar.gz | Restrict www-data write paths; FIM on /var/backups |
| Second implant via root cron | .sysmon/ + cron.d entry | FIM on /etc/cron*, /var/lib dot-dirs; auditd on cron file changes |
| Weak IR account | analyst/analysis (documented, acceptable for range) | Real IR accounts: key auth + MFA + vault checkout |

## IR workflow this exam tests

```bash
# 1. what did the wire see?
tshark -r http-session.pcap -Y http.request -T fields -e http.request.method -e http.request.uri
# 2. correlate with host evidence
grep -E 'upload|shell|exfil' /var/log/apache2/*.log
find /var/www -name '*.phtml' -o -name '*.php' -newermt '30 days ago'
# 3. hunt what the capture lacks
ls -la /var/lib/ /var/tmp/ | grep ' \.'; cat /etc/crontab; ls /etc/cron.d/
```

## Lessons

- A capture shows one channel; the host shows everything — never stop at the pcap
- Timeline correlation (pcap ↔ access.log ↔ mtime) turns artifacts into a story
- Persistence hunt = "what re-executes": cron, systemd, rc.local, profile.d
