# Cheatsheet — First Foothold

## Targets

- **target01** — one SSH service, one banner leak, one sudo misconfiguration

## Useful commands

```bash
nmap -sV -sC <target01>            # service + banner grab
ssh anything@<target01>            # the ssh banner shows pre-auth
ssh <user>@<target01>              # once the banner gives you creds
sudo -l                            # first thing on any shell
sudo <binary>                      # GTFOBins says which binaries shell out
```

## Concepts

- SSH `Banner` (issue.net) is sent BEFORE authentication — grabbing it is legit recon
- Loot readable files in `/etc` and `/opt` after login — admins leave notes
- `sudo -l` output is the intended privesc map; GTFOBins has the recipes
- Flags: user-level + root-level — foothold is only half the quest
