# Exam: Black Box

T1 assessment for the forensics track. `archive01` was compromised last
night. You have the box and one packet capture of the intruder's session —
everything else you derive yourself.

## Objectives

1. Reconstruct the intrusion from `/var/evidence/evidence.pcap`.
2. Get onto the host the way the intruder did and find their stash.
3. Prove the persistence mechanism and collect its flag.

## Rules of engagement

- Three flags: stash, user, persistence — plus your report.
- Deliverable: write your findings to `/home/analyst/report.txt` — compromised account + persistence mechanism.
- IR access to fetch the evidence: `ssh analyst@<archive01>` (pw `analysis`).
- The capture is your head start — read it properly before walking the host.

## Environment

- **Kali**: your analysis workstation
- **archive01**: the compromised host on the range LAN
