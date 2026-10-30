# Defense notes — Lateral Pressure

## Vulnerability 1 — Guest-readable share with credentials

- **Weakness**: `files01` exports a public SMB share containing
  `/backups/ws-creds.txt` — workstation creds sitting on an open share.
- **Detect**: Samba `log.smbd` shows guest connects + reads of the backup
  dir; audit the share for `guest ok = yes`.
- **Fix**: `guest ok = no`, valid-users scoping, and never store credentials
  on shared storage — vault them.
- **Verify**: `smbclient //files01/share -N` is refused.

## Vulnerability 2 — Credential reuse chain

- **Weakness**: ws creds leaked → ws note leaks DA creds. Each hop grants
  the next — one share collapses the domain.
- **Detect**: Windows 4624 logons from files01-adjacent sources; 4672
  (admin logon) on the DC outside change windows; lateral tool artifacts
  (PSEXESVC, remote svc creation — events 7045/4625).
- **Fix**: unique creds per machine, no plaintext DA notes, LAPS for local
  admin, tiered admin so ws creds can't reach the DC.
- **Verify**: leaked-cred replay fails on the next hop.

## Vulnerability 3 — DA credentials on a workstation

- **Weakness**: `C:\ops\dc-note.txt` on ws01 names the DA password — the
  workstation is the crown-jewel leak.
- **Detect**: file auditing on `C:\ops`; baseline scans for "pass|admin" in
  user-accessible paths.
- **Fix**: remove the note, rotate DA, PAW-only domain administration.
- **Verify**: no credential files readable by standard users on endpoints.
