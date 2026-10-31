# Signed & Confused

> **Track**: Web AppSec · **Tier**: 3 · **Estimated time**: ~30 min

## Scenario

`jwt01` runs a small reporting API. Authentication is JWT — signed,
stateless, and signed with a secret someone picked off the top of their
head. The API also checks *who you are* a lot less carefully than *what
you're asking for*.

## Objectives

1. Get a token — the API tells you the demo account if you ask nicely.
2. Read someone else's data through the export endpoint (the IDOR).
3. Learn why the token verifies, forge a better one, and take the
   restricted report.

## Environment

- **Kali**: your attack workstation (jwt_tool / hashcat on board)
- **jwt01**: flask reporting API on :80

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
