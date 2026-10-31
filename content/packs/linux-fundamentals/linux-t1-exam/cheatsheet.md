# Cheatsheet — The Onboarding Box

## Targets

- **onboarding01** — T1 exam target; ssh + a file-sharing service

## Useful commands

```bash
nmap -sV -sC <ip>
ftp anonymous@<ip>                  # anonymous read shares are a classic
curl http://<ip>/                   # or the http variant

find / -perm -4000 -type f 2>/dev/null   # SUID inventory
find / -perm -u=s -type f 2>/dev/null    # same thing, different syntax
sudo -l
```

## Concepts

- Loot-first: enumerate *every* open port before touching a wordlist
- Anonymous FTP/HTTP drops are how onboarding material leaks
- SUID + interpreter = instant root shell (GTFOBins has the recipe)
- Exam rule: every technique needed was taught this tier
