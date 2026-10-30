# Domain Join

> **Track**: Active Directory · **Tier**: 1 · **Estimated time**: ~55 min

## Scenario

A single-domain lab network: `corp.pentrain.local` runs on one Windows
Server 2022 DC. Somewhere in it is a service account that was created years
ago with a password nobody rotated. Enumerate the domain, roast it, own the
box.

## Objectives

1. Enumerate the domain — users, SPNs, shares
2. Roast the service account, crack its ticket
3. Land on the DC → `sysvol-flag` + `dc-flag`

## Environment

- **Kali**: your attack workstation
- **dc01**: Windows Server 2022, domain controller for `corp.pentrain.local`

> Note: first AD deploy takes a while — Windows template + domain promotion.

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
