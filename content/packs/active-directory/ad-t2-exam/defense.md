# Defense notes — The Corp Lan

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Guest share with domain creds | Anonymous → workstation shell | Auth on every share; creds in a vault |
| Notes naming kerberos weaknesses | Tells the attacker exactly what to roast | Ops docs never record "preauth off" without a fix ticket |
| svc-metrics: no preauth | AS-REP roast free of charge | Enable preauth everywhere; monitor 4768 type 0 |
| Domain creds on a linux share | Cross-OS intel leak | Per-system creds; domain accounts never on unix shares |

## Audit commands

```powershell
Get-ADUser -Filter {DoesNotRequirePreAuth -eq $true}
Get-ADUser -Filter {ServicePrincipalName -ne $null} -Properties ServicePrincipalName,MemberOf
```

```bash
# on the fileserver
smbstatus --shares; grep -n 'guest ok' /etc/samba/smb.conf
grep -rIlnE 'CORP|pass|cred' /srv/share/
```

## Detection

- 4624 type 3 logons from unfamiliar sources on ws01
- 4768 type 0 (preauth-less AS requests) for svc-metrics
- SMB guest sessions on files01 from non-service IPs
