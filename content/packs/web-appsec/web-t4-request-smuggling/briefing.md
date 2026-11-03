# Split-Second

> **Track**: Web AppSec · **Tier**: 4 · **Estimated time**: ~45 min

## Scenario

NorthBridge put a hardened edge proxy in front of their backend API. The
edge filters every request path — `/internal/*` never leaves the DMZ. But
edge and backend disagree about **where one request ends and the next
begins**. Disagreement is an exploit.

## Objectives

1. Smuggle a request to `GET /internal/flag` past the edge ACL and submit
   the flag it returns (`smuggle-flag`)
2. Prove a **state-changing** desync: get a `POST /internal/report`
   through to the backend (`trace-marker`)

## Environment

- **Kali**: your attack workstation
- **app01**: Debian host, only TCP/80 published — edge proxy, backend behind it

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
- No HTTP client will build this request for you — think in raw bytes.
