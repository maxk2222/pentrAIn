# Defense notes — Open Shares

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Guest-readable `[public]` share | Anyone on the network reads everything on it | `guest ok = no`, `map to guest = Never`; authenticate every share |
| Credentials in a runbook on that share | `svc-backup` password public → share + SSH access | Secrets in a vault; docs reference vault paths, never literal passwords |
| Password reuse across SMB and SSH | One leak, two compromises | Distinct credentials per service; prefer key-only SSH |
| SNMP v2 `public` read on everything | Hostname, contact, process list, planted memo — free recon | SNMPv3 (auth+priv), or restrict to a monitoring IP + unique community |
| `valid users` as the only control on `[finance]` | One leaked password = full access | Share ACLs + filesystem ACLs + rotated creds |

## Audit commands

```bash
# share-level exposure
testparm -s | grep -nE 'guest ok|map to guest|valid users|path ='
smbclient -L //localhost/ -N          # can you list shares anonymously?

# snmp exposure
grep -nE 'rocommunity|syslocation|syscontact|extend' /etc/snmp/snmpd.conf
snmpwalk -v2c -c public localhost system   # works from off-box = problem

# plaintext secret sweep on shares
grep -rIlnE 'passw|secret|token|cred' /srv/samba/ 2>/dev/null
```

## Detection

- Samba log (`/var/log/samba/log.*`) — anonymous connects and repeated auth failures
- snmpd queries from non-monitoring IPs (firewall counters / auditd)
- sshd: new source IPs successfully logging in as service accounts

## Further reading

- Samba `smb.conf` manual — `guest ok`, `map to guest`, `valid users`
- SNMPv3 `net-snmp-create-v3-user`
