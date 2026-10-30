# Defense notes — Domain Join

## Vulnerability 1 — Roastable service account

- **Weakness**: `svc-backup` has an SPN and a weak password; anyone with
  domain creds (or none, for AS-REP cases) can request its TGS ticket and
  crack it offline.
- **Detect**: Windows Event **4769** — RC4 (`0x17`) ticket requests for the
  service account from non-service hosts; cracking attempts leave no server
  logs (offline by design).
- **Fix**: long random service passwords (gMSA where possible), AES-only
  encryption types (`msDS-SupportedEncryptionTypes`), monitor 4769 for RC4.
- **Verify**: `impacket-GetUserSPNs` returns nothing crackable — AES tickets
  resist the wordlist.

## Vulnerability 2 — Service account over-privilege

- **Weakness**: `svc-backup` is effectively DA in this lab — backup tasks
  don't need Domain Admin.
- **Detect**: `net group "Domain Admins"` / 4728 group-add events; periodic
  privilege review would flag it.
- **Fix**: least privilege — dedicated backup account scoped to its shares,
  tiered admin model, PAWs.
- **Verify**: `Get-ADGroupMember "Domain Admins"` shows only real admins.

## Vulnerability 3 — Flags/scripts readable via SYSVOL

- **Weakness**: files under SYSVOL scripts are world-readable to domain
  users — classic cpassword-style leak location.
- **Detect**: share access auditing (4663) on the scripts dir.
- **Fix**: never store secrets in SYSVOL; remove stored creds, rotate all.
- **Verify**: `dir \\dc01\SYSVOL` as an unprivileged user shows no flag/cred
  files.
