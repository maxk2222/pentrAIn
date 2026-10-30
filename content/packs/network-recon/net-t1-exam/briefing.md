# Exam: Neighborhood Watch

T1 assessment for the network-recon track. Service enumeration, anonymous
access, credential reuse, and a sudo-scoped escalation — the whole tier in
one box.

## Objectives

1. Map every listening service on `gatekeeper01`.
2. Collect the flag in the anonymous file share.
3. Turn share contents into a shell, then root.

## Rules of engagement

- Three flags — one per skill stage: access, foothold, escalation.
- Nothing here requires tools you haven't used this tier.

## Environment

- **Kali**: your attack workstation
- **gatekeeper01**: the assessment target on the range LAN
