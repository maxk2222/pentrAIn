# Cheatsheet — Open Shares

## Targets

- **smb01** — file server; expect SMB plus at least one UDP management service

## Useful commands

```bash
nmap -sV --top-ports 1000 <ip>            # TCP surface
sudo nmap -sU --top-ports 200 <ip>        # UDP surface — don't skip
smbclient -L //<ip>/                      # list shares (anonymous)
smbclient //<ip>/<share>                  # connect; empty password for guest
smbclient //<ip>/<share> -U <user>        # authenticate
smbmap -H <ip>                            # share permissions overview
snmpwalk -v2c -c public <ip>              # full tree — system, processes, users
snmp-check <ip>                           # friendlier snmp summary (kali)
ssh <user>@<ip>                           # once you hold credentials
```

## Concepts

- UDP services (SNMP, TFTP, DNS) never show up in a TCP-only scan
- "read only" ≠ "harmless" — read access to the wrong file is a breach
- Service-account passwords get reused; try every cred on every door
