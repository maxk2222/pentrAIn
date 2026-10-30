# Three Hops Deep

> **Track**: Network & Recon · **Tier**: 3 · **Estimated time**: ~50 min

## Scenario

A classic three-tier deployment: `dmz01` faces the world, `app01` trusts only
the DMZ, `data01` trusts only the app tier. Your scan reaches exactly one of
them. Everything deeper has to be earned one hop at a time — each host was
configured by an admin who left the next hop's keys lying around.

## Objectives

1. Foothold on `dmz01` → `dmz-flag`
2. Pivot to `app01` → `app-flag`
3. Pivot to `data01` and go root → `data-flag`

## Environment

- **Kali**: your attack workstation
- **dmz01**: exposed (ssh + http)
- **app01**: accepts traffic only from dmz01
- **data01**: accepts traffic only from app01

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
