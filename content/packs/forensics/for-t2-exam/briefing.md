# Exam: Full Report

T2 assessment for the forensics track. `web01` got popped through its file
upload last week. IR handed you a packet capture of the noisy part and SSH
access to the box. Write the full timeline — including what the capture
doesn't show.

## Objectives

1. Reconstruct the intrusion from `/var/evidence/http-session.pcap`.
2. Find the webshell, the exfil staging, and their flags on disk.
3. Find the second implant — the one the attacker kept quiet about.

## Rules of engagement

- Three flags: webshell, exfil, persistence.
- You have IR access to web01: `ssh analyst@<web01>` (pw `analysis`,
  read-only — log access via the adm group).
- Deliverable: write your findings to `/home/analyst/report.txt` — attacker IP, webshell name, and the second implant.

## Environment

- **Kali**: your analysis workstation
- **web01**: the compromised web server
