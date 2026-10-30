# Behind the Firewall

> **Track**: Network & Recon · **Tier**: 2 · **Estimated time**: ~40 min

## Scenario

Two hosts share your VLAN, but only one talks to strangers: `edge01` answers
your probes, `internal01` drops every packet you send. Somewhere behind the
firewall is the real prize — the edge box is your stepping stone.

## Objectives

1. Get onto `edge01` → `edge-flag`
2. Pivot through it to `internal01` → `internal-flag`

## Environment

- **Kali**: your attack workstation
- **edge01**: exposed — ssh + http
- **internal01**: firewalled; only trusts edge01's address

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
