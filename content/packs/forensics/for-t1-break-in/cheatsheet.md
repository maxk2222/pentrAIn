# Cheatsheet — The Break-in

## Targets

- **evidence01** — compromised host; analyst/analyst for triage

## Useful commands

```bash
grep -E "Failed|Accepted" /var/log/auth.log | tail -30
cat /home/ops/.bash_history
ls -la /tmp/ /etc/cron.d/
find / -newermt "2024-03-14" ! -newermt "2024-03-16" -type f 2>/dev/null
```

## Concepts

- Failed→Accepted password pairs = brute force succeeding
- bash_history is the attacker's to-do list — read every line
- Cron persistence hides in plain sight in /etc/cron.d
- Two flags: the stash dir + the persistence mechanism's neighbor
