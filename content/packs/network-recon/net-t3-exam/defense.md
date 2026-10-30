# Defense notes — Three Doors Down

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Open AXFR + chatty TXT records | The network map is public | Restrict transfers; keep topology notes out of DNS |
| SNMP `public` + `extend` creds | Passwords broadcast over UDP 161 | SNMPv3; never echo credentials in extends |
| Creds in a public docroot | /docs/netplan.txt = both pivots' keys | Ops notes don't go in docroots; secrets vault |
| Source-IP-only vault policy | One dmz shell = vault root | Auth per tier + segmentation, and no reused jump accounts |
| Full sudoer on the innermost host | Final flag trivially root | Scope sudoers to actual duties |

## Audit commands

```bash
dig @<edge> corp.local axfr | grep -iE 'txt|pass|cred'
snmpwalk -v2c -c public <edge> | grep -iE 'cred|pass|login'
curl -s http://<dmz>/docs/ | grep -iE 'pass|cred|vault'
nft list ruleset on vault01 — verify only dmz/router sources
```

## Detection

- named query log: AXFR from foreign IPs
- vault auth.log: logins whose source isn't dmz01 — impossible means spoofed
- dmz access.log: GETs on *.txt under /docs from non-corp IPs
