# Exam: First Contact

T1 assessment for the active-directory track. One domain controller, every
T1 primitive on the table: domain enumeration, SYSVOL looting, and BOTH
roast types — the SPN account and the one that never needed preauth.

## Objectives

1. Enumerate `corp.pentrain.local` — users, SPNs, shares.
2. Loot SYSVOL for the first flag.
3. Roast two service accounts, crack them, and reach the domain flag.

## Rules of engagement

- Three flags: SYSVOL, roast, domain.
- Both roast primitives are required knowledge — check which account
  responds to which technique.

## Environment

- **Kali**: your attack workstation
- **dc01**: the corp.pentrain.local domain controller
