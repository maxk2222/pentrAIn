# Post Mortem

> **Track**: Forensics · **Tier**: 2 · **Estimated time**: ~30 min

## Scenario

`web01` served a small shop CMS until last night, when monitoring caught an
outbound archive transfer. The box is preserved for analysis: rebuild the
attack — entry vector, dropped tools, what left the building — and recover
the two flags hidden in the evidence.

## Objectives

1. Identify the entry vector from `access.log` (it was a SQLi)
2. Locate the dropped webshell → `webshell-flag`
3. Find the attacker's loot staging → `exfil-flag`

## Environment

- **Kali**: analysis workstation — `ssh analyst@<web01>` (pw `analysis`,
  NOPASSWD sudo for reading)
- **web01**: the compromised web server, preserved

## Rules of engagement

- Blue quest: analyze, don't attack.
- Deliverable: write your findings to `/home/analyst/report.txt` — attacker IP + webshell filename.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
