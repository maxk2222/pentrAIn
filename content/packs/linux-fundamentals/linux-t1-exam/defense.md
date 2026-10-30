# Defense notes — The Onboarding Box

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| World-readable credential note | Free SSH for anyone on the wire | Never provision passwords in files; use a secrets handoff (vault, 1Password share, first-boot prompt) |
| SUID on `/usr/bin/python3` | Any local user gets a full root shell | Audit SUID: only binaries that genuinely need it; `chmod u-s` the rest |
| Password auth on sshd | Looted creds = instant shell | Key-only auth for service+human accounts |

## Audit commands

```bash
find / -perm -4000 -type f 2>/dev/null        # every SUID binary — diff vs baseline
grep -rIlnE 'pass|cred' /opt /srv /var /etc 2>/dev/null
find / -xdev -type f -name '*welcome*' -o -name '*.txt' -readable 2>/dev/null | head
```

## Detection

- `ausearch -k suid_abuse` — auditd rules on execve of SUID binaries by non-root
- auth.log: first-time logins from unexpected source IPs
- FIM alerts on mode changes to 4xxx on system binaries
