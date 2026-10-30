# The Perimeter

> **Track**: Network & Recon · **Tier**: 1 · **Estimated time**: ~30 min

## Scenario

A legacy services host was found on the assessment VLAN. It was never
hardened — every default it shipped with is still there. Enumerate it
methodically; each open service is a door, and one of them leads to
credentials for the next.

## Objectives

1. Enumerate all listening services (`ftp-flag` is on the anonymous share)
2. Find the hidden web directory (`web-flag`)
3. Pivot through the database to a shell account (`dbadm-flag`)

## Environment

- **Kali**: your attack workstation
- **svc01**: target host on your VLAN

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
