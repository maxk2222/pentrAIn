# Defense notes — First Foothold

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Weak password (`student123`) | Trivial SSH brute-force / guessable login | Enforce a password policy (min 14 chars, complexity), run `pam_pwquality`, rotate on compromise |
| Credentials in world-readable files | `/etc/backup-notes.txt` leaks the login to anyone on the box | Never store secrets in `/etc`; use a secrets manager or `0600 root:root` files |
| `NOPASSWD` sudo on `vim` | Instant root via `sudo vim -c ':!sh'` | Sudoers should list *specific* needed commands, never editors/shells; require passwords |
| Password authentication enabled | Weak creds become remotely exploitable | Prefer `PasswordAuthentication no` + SSH keys |

## Hardening checklist

```bash
# 1. audit sudoers
visudo                      # remove NOPASSWD entries for editors/shells
sudo -l -U student          # review what a user may run

# 2. lock down auth
passwd -l student           # disable the account or set a strong password
sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

# 3. find leaked secrets
grep -rIln 'passw\|secret' /etc /opt /srv 2>/dev/null
chmod 600 /etc/backup-notes.txt; chown root:root /etc/backup-notes.txt

# 4. monitor for abuse
apt install auditd
auditctl -w /etc/sudoers.d -p wa -k sudoers_changes
```

## Detection signals

- `sudo` executions of editors/interpreters → alert (`usersudoers` style rules, auditd on `/usr/bin/vim` executions by non-root)
- New SSH logins for service/training accounts → journald watcher
- GTFOBins binaries in `ps` with root parent

## Further reading

- GTFOBins — `vim`: https://gtfobins.github.io/gtfobins/vim/
- CIS Debian Benchmark, sections on sudo and SSH
