# Cheatsheet — Full Report

## Targets

- **web01** — popped web server; IR access `ssh analyst@` (pw `analysis`)

## Useful commands

```bash
tshark -r /var/evidence/http-session.pcap -Y http -V | less
tshark -r http-session.pcap -Y http.request -T fields -e http.request.uri
tshark -r http-session.pcap -q -z follow,tcp,ascii,0

# host-side correlation
grep -iE 'upload|shell|exfil|404|500' /var/log/apache2/*access*.log
find /var/www -type f \( -name '*.phtml' -o -name 'shell*' \)
tar tzf /var/backups/exfil.tar.gz            # list what was staged
ls -la /var/backups/

# persistence sweep — what re-executes?
cat /etc/crontab; ls -la /etc/cron.d/ /etc/cron.*/ 
systemctl list-unit-files --type=service | grep -vE 'enabled|disabled'
ls -la /var/lib/ /var/tmp/ | grep ' \.'
find / -xdev -name '*.sh' -newermt '60 days ago' 2>/dev/null
```

## Concepts

- Pcap = channel view; host = ground truth — reconcile both
- webshell forensics: filename in log ↔ file on disk ↔ payload in capture
- The flag you *don't* see in the capture is usually the interesting one
