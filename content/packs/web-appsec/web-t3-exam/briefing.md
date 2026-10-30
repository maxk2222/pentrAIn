# Exam: The Reporting API

T3 assessment for the web-appsec track. A small reporting API on `api01`
issues JWTs, keeps user exports behind an integer, and trusts claims it
shouldn't. Turn it into command execution.

## Objectives

1. Map the API and authenticate — a low-priv account is documented in the
   service itself.
2. Read another user's export (IDOR flag).
3. Forge an admin token and take both remaining flags.

## Rules of engagement

- Three flags: IDOR, admin endpoint, host file.
- The JWT secret is weak by design — crack, forge, chain.

## Environment

- **Kali**: your attack workstation
- **api01**: the reporting API on port 80
