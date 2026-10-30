# Enterprise

> **Track**: Active Directory · **Tier**: 3 · **Estimated time**: ~90 min

## Scenario

The full corporate picture: `corp.pentrain.local` on two DCs (one a
replica), two domain-joined workstations — and an ops team that writes
credentials into notes, scripts, and readmes. Work the entire kill chain:
local admin on a workstation, lateral movement, a service account, DC
compromise, and the replica at the end.

## Objectives

1. Workstation foothold → `ws-flag`
2. Reuse + move → `ws2-flag`
3. Domain Admin → `dc-flag`
4. The replica DC → `forest-flag`

## Environment

- **Kali**: your attack workstation
- **dc01 / dc02**: Windows Server 2022 domain controllers (dc02 = replica)
- **ws01 / ws02**: Windows 11 domain-joined workstations

> Flagship quest — 4 windows VMs + DC promotion: deploy is slow, requirements
> are real (48G RAM). Plan the session.

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `PenTrAIn{...}` — submit them in the Flags panel.
