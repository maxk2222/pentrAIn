# Cheatsheet — Black Box

## Targets

- **archive01** — compromised host; capture at /var/evidence/evidence.pcap

## Useful commands

```bash
capinfos /var/evidence/evidence.pcap
tshark -r evidence.pcap -q -z conv,tcp        # who talked to whom
tshark -r evidence.pcap -Y ftp -V | less      # cleartext gold
tshark -r evidence.pcap -Y 'ftp.request' -T fields -e ftp.request.arg
strings evidence.pcap | grep -iE 'pass|user|\.sh|service'

# on the host
cat ~/.bash_history; ls -la /var/tmp/ /var/lib/ | grep ' \.'
systemctl list-unit-files | grep -vE 'disabled|enabled'   # odd units
find / -xdev -name 'persist*' -o -name '*.service' -newermt '1 day ago' 2>/dev/null
```

## Concepts

- Cleartext protocols hand you the whole story — read before you touch
- bash_history survives `history -c` on disk until the session ends
- Persistence = anything that re-executes: cron, systemd, profile.d, ld.so
