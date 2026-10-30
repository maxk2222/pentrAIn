# Correlated

> **Track**: Forensics · **Tier**: 3 · **Estimated time**: ~45 min

## Scenario

A full intrusion across three hosts: entry on `edge01`, lateral movement to
`app01`, data staging on `db01`. Each host holds one stage of the attacker's
camp — find all three flags and reconstruct the kill chain end to end.

## Objectives

1. Entry: which account fell on `edge01` → `entry-flag`
2. Lateral: the pivot path to `app01` → `pivot-flag`
3. Exfil: what was staged on `db01` → `exfil-flag`

## Environment

- **Kali**: analysis workstation — `ssh analyst@<host>` (pw `analysis`,
  NOPASSWD sudo) to each of the three hosts
- **edge01 / app01 / db01**: the compromised chain, preserved
- `db01` also collected forwarded syslog in `/var/log/collected.log`

## Rules of engagement

- Blue quest: analyze, don't attack.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
