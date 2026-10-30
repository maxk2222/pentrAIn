# Exam: The Intranet

T2 assessment for the web-appsec track. One app, the whole kill chain:
injection, filter evasion, code execution.

## Objectives

1. Get past the intranet login without credentials.
2. Reach the document upload and defeat its extension filter.
3. Execute code on the host and collect the flag outside the webroot.

## Rules of engagement

- Three flags: behind the login, in the drop dir, behind RCE.
- Everything required was taught this tier — this is a chain, not a puzzle.

## Environment

- **Kali**: your attack workstation
- **intranet01**: the assessment target on the range LAN
