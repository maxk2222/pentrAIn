# Linux fundamentals — reference card

Quick syntax for enumeration, shells and privilege escalation.

## Enumeration

```bash
nmap -sV -sC -p- <ip>              # full port scan + default scripts
ss -tulpn                          # listening sockets on the box
find / -perm -4000 -type f 2>/dev/null   # SUID binaries
sudo -l                            # what can this user run as root
crontab -l; ls -la /etc/cron*      # scheduled jobs
cat /etc/passwd; getent passwd     # local users
```

## Privilege escalation probes

- `sudo -l` first — a NOPASSWD binary is the intended path 9 times out of 10
- SUID: cross-check against GTFOBins (`find`, `vim`, `cp`, `tar` are classics)
- Writable scripts run by cron → inject your payload, wait a cycle
- Kernel exploits last — check `uname -a`, then searchsploit

## Shell hygiene

```bash
python3 -c 'import pty; pty.spawn("/bin/bash")'   # upgrade to a pty
export TERM=xterm; stty raw -echo; fg             # full TTY after ^Z
```

## Worth remembering

- GTFOBins is your cheat sheet inside the cheat sheet
- `2>/dev/null` on every `find` — permission noise hides the hits
- Look for `*backup*`, `*.bak`, `.git/` — creds love leftovers
