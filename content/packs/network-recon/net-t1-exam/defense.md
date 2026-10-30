# Defense notes — Neighborhood Watch

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Anonymous FTP | Every hosted file is public | `anonymous_enable=NO`; move files to authenticated SFTP |
| Guest SMB share with credentials | Door key published on the LAN | `guest ok = no` + real ACLs; never store passwords in shares |
| `sudo find` NOPASSWD | Any local user is root | Drop the sudoers entry; ship logs via a dedicated service account |
| Weak password on fieldtech | Share leak → shell | Unique strong password + key auth |

## Audit commands

```bash
nmap -p 21,22,139,445 <host> --script ftp-anon,smb-enum-shares
smbclient -N -L //<host>
grep -rn 'NOPASSWD' /etc/sudoers /etc/sudoers.d/
grep -nE 'anonymous_enable|anon_root' /etc/vsftpd.conf
```

## Detection

- vsftpd: anonymous logins in /var/log/vsftpd.log
- smbd: guest sessions from unknown IPs
- sudo: `find` executions in auth.log (root shells follow)
