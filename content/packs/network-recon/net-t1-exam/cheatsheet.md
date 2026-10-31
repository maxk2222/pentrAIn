# Cheatsheet — Neighborhood Watch

## Targets

- **gatekeeper01** — ftp + smb + ssh; one flag per skill stage

## Useful commands

```bash
nmap -sV -sC <ip>
ftp <ip>                       # try anonymous
smbclient -N -L //<ip>         # list guest shares
smbmap -H <ip> -u guest
ssh <user>@<ip>
sudo -l                        # GTFOBins lookup for whatever appears
```

## Concepts

- Anonymous access is a finding, not a dead end — pull *everything*
- Shares leak the human layer: creds, hostnames, procedures
- `sudo <gtfobin>` is the cheapest privesc there is — always check `sudo -l`
