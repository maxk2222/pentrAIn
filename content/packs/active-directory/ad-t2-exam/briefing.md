# Exam: The Corp Lan

T2 assessment for the active-directory track. The classic chain, plus one
exam-day surprise: a linux fileserver's guest share, a domain workstation,
a domain controller — and a service account whose kerberos settings were
"temporarily" relaxed.

## Objectives

1. Loot `files01`'s share for everything it offers (two notes, one flag).
2. Land on `ws01` with the leaked creds — collect its flag.
3. Roast `svc-metrics` from the domain and reach `dc01`'s flags.

## Rules of engagement

- Four flags: files, workstation, roast, domain.
- The corp chain from the tier applies — read both notes on the share.

## Environment

- **Kali**: your attack workstation
- **files01**: linux fileserver (the intel source)
- **ws01**: domain workstation (the middle hop)
- **dc01**: domain controller (the prize)
