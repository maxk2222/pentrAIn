# Cheatsheet — Correlated

## Targets

- **edge01 / app01 / db01** — three-host intrusion chain, shared subnet
- Central syslog stream lands in `/var/log/collected.log` on db01

## Useful commands

```bash
grep <attacker-ip> /var/log/auth.log            # per host
sort -m /var/log/collected.log | less           # merged timeline
cat /home/*/.bash_history | grep -nE "ssh|scp"  # the hops
```

## Concepts

- One IP strings all three hosts together — pivot creds travel in history
- collected.log aligns edge→app→db events into a single kill-chain
- Correlate by timestamp AND source — false hits drop out fast
