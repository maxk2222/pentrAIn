---
id: minimal-hosts
title: Working on minimal target VMs — missing tools & universal fallbacks
triggers: [command not found, not found, missing:, minimal, busybox]
---

# Minimal target VMs

Target VMs are MINIMAL debian — no tshark/strings/tcpdump/forensics
tools there. `missing:<tool>@<host>` entries in FACTS mark what is
absent on which host — never retry them.

Probe tool availability ONCE per host and remember it:

```bash
command -v curl wget python3 nc nmap git base64
```

"command not found" NEVER fixes itself — retrying the same missing tool
on the same host is a wasted turn.

## Universal fallbacks (almost always present)

- HTTP without curl/wget:

  ```bash
  python3 -c "import urllib.request as u;print(u.urlopen('http://x/').read().decode())"
  ```

- Port probe without nmap/nc: `bash -c 'echo > /dev/tcp/<ip>/<port>' && echo open`
- File transfer: `cat`, `base64` — pull evidence to Kali first
  (`sshpass -p … scp … /tmp/` or `ssh … 'cat file' > /tmp/file`),
  analyze locally; scp needs `-o StrictHostKeyChecking=no` or it fails
  on the unknown hostkey.
- Heavier analysis (forensics, tshark, crackers) belongs on Kali — the
  targets are for reaching, not for tooling.
