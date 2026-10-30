# Coach context — Enterprise

## Intended path

1. Recon: `nmap` the .51/.53/.54/.55 hosts — DCs on .51/.54 (88/389/445/636),
   workstations on .53/.55.
2. `ws01`: local admin `wadmin/WAdmin2024!` is in `C:\ops\readme.txt`
   (leaked via the share/page or guessable path) → `ws-flag`.
3. ws01's readme names `ws02`'s local admin — same `WAdmin2024!` (reuse
   lesson) → `ws-flag`→`ws2-flag` at `C:\flags\ws02.txt`.
4. ws02: `C:\helpdesk\dc-script.ps1` contains `svc-rep / RepSvc2024!` — a
   **domain admin** service account → `evil-winrm`/psexec to dc01 →
   `C:\flags\dc01.txt` → **dc-flag**; `secretsdump`/dcsync for the crown.
5. Same DA creds hit `dc02` (replica DC, identical domain) →
   `C:\flags\forest.txt` → **forest-flag**.

## Key facts (stage 2–3 only)

- Cred chain: `wadmin/WAdmin2024!` (ws01+ws02 local) →
  `svc-rep/RepSvc2024!` (Domain Admin, both DCs).
- Leak locations: `C:\ops\readme.txt` (ws01), `C:\helpdesk\dc-script.ps1`
  (ws02).
- dc02 is a replica — same domain, same DA creds; it's the last flag, not a
  new domain.
- All flags file-based via qemu-ga; trainees read + submit `PenTrAIn{...}`.

## Common wrong turns

- Hitting the DCs first — entry is designed around the workstations.
- Treating ws02 as skippable — `dc-script.ps1` there is the DA pivot.
- Assuming dc02 needs separate creds — it's the same domain (replica).
