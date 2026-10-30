# Defense notes — Zone Out

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `allow-transfer { any; }` | Whole zone — every hostname — public | Restrict AXFR to secondaries only: `allow-transfer { <secondary-ips>; };` + TSIG |
| SNMP `public` with full read tree | Hostname, contacts, account names, process list | SNMPv3 auth+priv, or a unique community + ACL to the monitoring host |
| `extend` leaking job details | `backup-memo` names the service account | Don't expose operational detail via SNMP; least-info principle |
| TFTP without authentication | Anyone pulls everything in /srv/tftp | Replace with SFTP; if TFTP is required, chroot + firewall to known peers |
| Weak service password | `backup123` falls to a small wordlist | Strong unique password + `PasswordAuthentication no` + fail2ban |

## Audit commands

```bash
# would a stranger get your zone?
dig @<dns> <zone> axfr +short | head        # non-empty = misconfig
named-checkconf -z | grep -i transfer
grep -n 'allow-transfer' /etc/bind/*

# snmp surface
snmpwalk -v2c -c public <ip> system
grep -nE 'rocommunity|extend' /etc/snmp/snmpd.conf

# tftp inventory
ls -l /srv/tftp; grep -n 'TFTP_DIRECTORY' /etc/default/tftpd-hpa
```

## Detection

- named query.log: AXFR requests (`transfer`) from non-secondary IPs
- snmpd: polls from unknown IPs (no auth logging — count via firewall)
- sshd: bursts of failed logins = brute-force signature (fail2ban watches this)

## Further reading

- DNS zone transfers & why `allow-transfer` defaults matter
- SNMPv3 vs v2c — authentication and encryption
