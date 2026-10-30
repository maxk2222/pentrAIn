# Defense notes — First Contact

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| svc-backup: SPN + DA + weak password | Kerberoast → DA | Long machine-generated passwords; gMSA; don't put SPNs on DA accounts |
| svc-report: preauth disabled | AS-REP roast → instant hash, no auth needed | Never disable preauth; audit `DoesNotRequirePreAuth` |
| SYSVOL scripts readable by all | Foothold intel free | Review sysvol contents — treat as public |
| Passwords in the wordlist | Both accounts crack in seconds | Passphrase policy ≥20 chars for service accounts |

## Audit commands

```powershell
Get-ADUser -Filter {DoesNotRequirePreAuth -eq $true}
Get-ADUser -Filter {ServicePrincipalName -ne $null} -Properties ServicePrincipalName
Get-ADUser svc-backup -Properties MemberOf | select -Expand MemberOf
```

## Detection

- Event 4768 with preauth type 0 = AS-REP roast attempt
- Event 4769 for RC4 TGS requests on honeypot SPNs
- Password spray: many 4625 failures followed by one 4624 success
