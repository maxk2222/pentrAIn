# Defense notes — Supply Chain

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Creds in motd/runbooks/configs | Every hop hands the next one's key | Secrets in a vault; runbooks reference the vault, not passwords |
| Password auth on every tier | Creds = instant shells | Key-only + per-tier keys; bastion as the only entry |
| `sudo journalctl` NOPASSWD | Pager escape → root | Drop the scope; journald group membership instead |
| Full sudoer `dba` | db01 root in one command | dba needs db admin, not OS root — scope sudoers |
| Source-IP segmentation as the only barrier | One bastion cred = everything | Segmentation + auth, not instead of it |

## Audit commands

```bash
grep -rIlnE 'pass|cred' /etc/motd /home/*/DEPLOY* /opt/*/config* 2>/dev/null
grep -rn 'NOPASSWD\|ALL=(ALL)' /etc/sudoers /etc/sudoers.d/
nft list ruleset | grep -B2 -A8 'chain input'   # review every accept rule
```

## Detection

- auth.log on each tier: logins whose source isn't the expected previous hop
- `sudo` executions of journalctl followed by shell spawns
- Bastion egress: ssh sessions from the bastion user to non-deploy targets

## Lessons

- Tiered networks fail closed only when BOTH the firewall and the auth model hold
- Every config file is a credential store — treat permissions accordingly
