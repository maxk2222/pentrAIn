# Exam: The Whole Incident

T3 assessment for the forensics track. Two hosts were hit in one night:
`web02` loudly, `db02` quietly. You have IR access to both — correlate
everything into one timeline and recover the three flags.

## Objectives

1. Reconstruct the initial intrusion on `web02` (capture + logs agree).
2. Prove the lateral move to `db02` — which account, from where, when.
3. Recover the staged loot and the abused account's flag.

## Rules of engagement

- IR access on both hosts: `ssh analyst@<host>` (pw `analysis`, read-only
  with log access via the adm group).
- Deliverable: write your findings to `/home/analyst/report.txt` on **db02**
  — abused account and where the loot was staged.
- Four flags: webshell, loot, account — plus the report.
- The deliverable is the *timeline*: pcap ↔ access.log ↔ auth.log.

## Environment

- **Kali**: your analysis workstation
- **web02**: the popped web server
- **db02**: the quietly touched database host
