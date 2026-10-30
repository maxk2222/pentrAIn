# Exam: Perimeter Audit

T2 assessment for the network-recon track. Two boxes: `edge01` is a chatty
perimeter host; `internal01` pretends it doesn't exist — it drops every
packet that doesn't come from the edge.

## Objectives

1. Interrogate the edge's UDP services and take what they hand out.
2. Pull the free flag from the unauthenticated file service.
3. Use what the edge tells you to reach the internal host — both flags.

## Rules of engagement

- Three flags: tftp, internal-user, internal-web.
- `internal01` only accepts edge-originated traffic — no exceptions.
- The credentials you need exist; you just have to ask the right service.

## Environment

- **Kali**: your attack workstation
- **edge01**: perimeter host, DNS/SNMP/TFTP/SSH
- **internal01**: the walled-off build server
