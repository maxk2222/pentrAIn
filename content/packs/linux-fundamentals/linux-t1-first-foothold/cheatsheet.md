# Cheatsheet — First Foothold

## Targets

- **web01** — one web service, one misconfiguration, one flag

## Useful commands

```bash
nmap -sV -sC <web01>
gobuster dir -u http://<web01>/ -w common.txt
curl -s http://<web01>/robots.txt
ssh user@<web01>                # creds hide where they shouldn't
sudo -l                         # first thing on any shell
```

## Concepts

- Robots.txt / backup files / readable home dirs — the tier-1 trinity
- `sudo -l` output is the intended privesc map
- Flags: user-level + root-level — foothold is only half the quest
