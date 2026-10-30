# Defense notes — Enterprise

## The kill chain

`ws01` (local admin in `C:\ops\readme.txt`) → reused password lands `ws02` →
`C:\helpdesk\dc-script.ps1` on ws02 leaks `svc-rep` DA creds → `dc01` →
`dc02` (replica, same domain — DA creds work everywhere).

## Vulnerabilities

- **Local admin password reuse**: ws01's readme password also owns ws02 —
  the classic LAPS-shaped hole.
- **Service account DA + script leak**: `svc-rep` (Domain Admin) had its
  password embedded in a helpdesk powershell script on a workstation.
- **Uniform domain-trust surface**: DA creds work on every DC — no tiering.

## Detection

- 4624/4672 admin logons at odd hours from workstations to DCs
- 7045 service creation / remote exec artifacts (PsExecSvc)
- 4662 replication rights access on the DC (DCSync footprint) — the single
  most valuable alert for this chain
- File auditing on `C:\ops`, `C:\helpdesk` for readme/script access

## Fixes

- LAPS everywhere; unique local admin passwords per host
- No DA service accounts; gMSA + tiered admin + PAWs
- Remove creds from scripts; scan endpoints for embedded secrets
- Alert on 4662 replication access by non-DCs

## Verify

- `impacket-secretsdump` from a workstation fails (no DA creds left to leak).
- ws01↔ws02 local admin passwords differ after LAPS rollout.
