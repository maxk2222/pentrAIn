# Defense notes — Black Box

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Cleartext FTP | Credentials and ops notes readable on the wire | SFTP/FTPS only; `ftp`/`vsftpd` off the host |
| Password reuse | One sniffed password → interactive shell | Unique passwords + key auth; rotate on exposure |
| Persistence in plain sight (with a dot-dir costume) | `fonts-cache.service` survives reboots | FIM on /etc/systemd/system + /var/lib; alert on new units |
| History trail intact | bash_history mapped the stash for us | Attackers wipe logs — centralized logging off-box preserves evidence |

## IR checklist

```bash
# what did the wire see?
tshark -r evidence.pcap -Y 'ftp.request' -T fields -e ftp.request.command -e ftp.request.arg

# on the host:
last -a; grep -iE 'session opened|accepted' /var/log/auth.log | tail
find / -xdev -newermt '24 hours ago' -type f 2>/dev/null | grep -vE '^/(proc|sys|dev|run)'
ls -la /etc/systemd/system/ /etc/cron.* /var/spool/cron/
cat /home/*/.bash_history 2>/dev/null
```

## Lessons

- Packet captures beat host artifacts for attribution — capture at the edge
- Dot-directories and benign names (`fonts-cache`) are the cheapest disguise
- Correlate: pcap says *what*, logs say *when*, filesystem says *where*
