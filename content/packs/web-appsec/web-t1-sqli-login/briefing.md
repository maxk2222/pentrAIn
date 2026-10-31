# Trusting Query

> **Track**: Web AppSec · **Tier**: 1 · **Estimated time**: ~25 min

## Scenario

`sqli01` hosts an employee portal still in "IT testing." The developer
concatenates user input straight into the SQL — no parameters, no prepared
statements. Classic, fatal, and still the most common auth bypass in the
wild.

## Objectives

1. Map the endpoints — the login form is not the only input.
2. Bypass the login and take the flag the portal renders for members.
3. Use the rendered-results endpoint to pull a second credential out of
   the database — then prove it works on the host.

## Environment

- **Kali**: your attack workstation
- **sqli01**: apache + php + sqlite portal

## Rules of engagement

- Only attack hosts inside your deployed range.
- Flags look like `pentrAIn{...}` — submit them in the Flags panel.
