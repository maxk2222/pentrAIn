# Defense notes — Domain Takeover

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `Summer2024!` on jholt | One spray → domain user | Ban-list seasonal passwords; MFA; smart lockout |
| Onboarding.txt names the user | Attacker's user list, pre-built | SYSVOL is public — no account intel in scripts |
| Roastable service accounts | Creds → escalation | gMSA or ≥20-char machine passwords |
| Excessive delegation/admin rights | The path exists to be walked | Tiered admin; clean up ACLs; monitor delegation |
| Single DC mindset | dc02 went down with the domain | DCSync affects all replicas — monitor 4662 replication rights |

## Audit commands

```powershell
# who can be sprayed — weak-password audit
Get-ADUser -Filter * | Test-PasswordQuality   # or DSInternals Test-PasswordQuality
Get-ADObject -Filter 'msDS-AllowedToDelegateTo -like "*"' -Properties msDS-AllowedToDelegateTo
Get-ADUser -Filter {DoesNotRequirePreAuth -eq $true}
# replication rights — who can DCSync?
(Get-Acl "AD:\DC=corp,DC=pentrain,DC=local").Access | ? {$_.ActiveDirectoryRights -match 'Replicating'}
```

## Detection

- 4771 failures in bursts = spray pattern (then one 4768 success)
- 4662 replication requests from non-DC accounts = DCSync
- Bloodhound noise: LDAP query storms + session enumeration SMB connects
