# Defense notes — Sticky Bits

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Plaintext credentials in a doc | `/opt/onboarding/login-credentials.txt` = free SSH | Secrets in a vault; onboarding rotates a one-time token, not a static password |
| `chmod u+s` on `base64` | Any user reads any file as root — no shell needed | Remove the bit; SUID only where strictly required and audited |
| Uninventoried setuid binaries | `sysdiag` + `base64` nobody reviewed | Baseline `find / -perm -4000` and alert on drift |
| Password auth on SSH | Leaked password = remote shell | Key-only auth (`PasswordAuthentication no`) |

## Audit commands

```bash
# SUID/SGID baseline — diff against a known-good list
find / -xdev \( -perm -4000 -o -perm -2000 \) -type f -ls 2>/dev/null

# strip the offending bit
chmod u-s /usr/bin/base64

# plaintext secret sweep
grep -rIlnE 'passw|cred|token' /opt /etc /srv /home 2>/dev/null

# capabilities are a subtler variant of the same problem
getcap -r / 2>/dev/null
```

## Detection

- auditd: watch execve of known file-read GTFOBins by non-root users
- file integrity monitoring (AIDE/Tripwire) on `/usr/bin` permission changes
- alert on `base64`/`cp`/`vim`/`find` spawning with euid 0 by unprivileged users

## Further reading

- GTFOBins — https://gtfobins.github.io/ (the `base64` file-read entry)
- CIS Debian benchmark — "Audit SUID executables"
