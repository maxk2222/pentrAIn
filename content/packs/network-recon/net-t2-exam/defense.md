# Defense notes — Perimeter Audit

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `allow-transfer { any; }` | Whole zone — including a TXT record with credentials | Restrict AXFR to secondaries + TSIG; never put secrets in DNS |
| Secrets in a TXT record | The zone *is* the credential leak | DNS is public data even when AXFR is restricted — no secrets ever |
| SNMP `public` | Hostname, contacts, topology hints | SNMPv3 auth+priv + ACL to the monitoring host |
| Unauthenticated TFTP | Free file pull | SFTP; if TFTP is mandatory, chroot + firewall to known peers |
| Same creds on edge + internal | One leak, two shells | Per-host credentials; edge accounts should never reach internal |

## Audit commands

```bash
dig @<dns> corp.local axfr +short | head       # zone leakage check
dig @<dns> internal.corp.local txt +short      # TXT records carry no secrets
snmpwalk -v2c -c public <edge> system
nft list ruleset | grep -A5 'chain input'      # verify the segmentation intent
grep -nE 'rocommunity|extend' /etc/snmp/snmpd.conf
```

## Detection

- named: AXFR requests from non-secondary IPs
- internal01: dropped-packet counter on the input chain = scan noise
- auth.log on edge: netops logins from non-jump sources
