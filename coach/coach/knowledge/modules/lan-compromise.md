---
id: lan-compromise
title: LAN host compromise — service surface attacks & NAT reality
triggers: [nmap scan report, arp-scan, NetBIOS, 445/tcp, 2049/tcp, showmount, smbclient, 3389/tcp, 5985/tcp, router, NAT]
---

# Compromising hosts on a flat LAN

Work a kill chain, not random ports: enumerate → fingerprint → pick the
juiciest service → attack → prove → document.

## Discovery & fingerprinting

- `arp-scan -l` / `netdiscover` — every L2 neighbor (works where ICMP is
  filtered)
- `nmap -sV -O --osscan-guess <ip>` — OS+services; TTL hints: ~64 Linux,
  ~128 Windows, ~255 network gear
- NetBIOS names: `nbtscan <subnet>` — Windows boxes announce
  `DESKTOP-*`/`WIN-*`/`WORKGROUP`; silent = probably not Windows
- DHCP hostnames: `dig -x <ip> @<router>` — client names leak OS/family

## Per-service attack paths

- **NFS (2049)**: `showmount -e <ip>` → `mount -t nfs <ip>:/<share> /mnt`
  → if writable, drop `PWNED.txt` — world-writable export = file-write
  primitive on the host (uid may be squashed but the write still proves
  access). `no_root_squash` gives real root writes.
- **SMB (139/445)**: `smbclient -N -L //<ip>/` (null session),
  `enum4linux-ng <ip>`, `smbmap -H <ip>` → writable share = proof;
  creds → `smbclient //<ip>/<share> -U user`, `psexec`-style exec only
  on Windows.
- **RDP (3389) / WinRM (5985-6)**: Windows-only remote access —
  `xfreerdp /v:<ip> /u:x /p:y`, `evil-winrm -i <ip> -u x -p y`. Closed
  ≠ hardened Windows: firewalled Windows answers NO TCP but still
  NetBIOS/LLMNR on UDP 137/5355.
- **SSH (22)**: key-found-in-loot > brute force; `hydra` only as last
  resort and log the attempt honestly.
- **Router/AP (80/443/7547 TR-069)**: try default/common creds on the
  admin panel, check UPnP/SNMP — a compromised gateway owns the whole
  segment (port forwards, DNS, routes).

## NAT & segmentation reality — proof beats persistence

A host behind a second NAT router is **not inbound-reachable**: no
route, no ARP entry, every WAN-side port filtered. Prove the wall
ONCE concretely (scan ` -p-` on the NAT IP, check routes/DHCP table),
record the negative as evidence, and pivot strategy (compromise the
router's admin plane, or find a host that can reach it) — do NOT burn
turns re-scanning an unreachable target hoping it changes.

## Verify compromise — evidence, not vibes

Real access = a reversible primitive: write `/tmp/PWNED.txt` (or
`C:\PWNED.txt`) on the target and read it back, execute a command,
dump a hash. Report the exact primitive. "Port open" is never
compromise. If nothing worked, report the negative honestly — a
verified "not reachable/vulnerable" is a correct pentest result.
