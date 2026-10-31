# Wiretap

Incident #2214. The NIDS recorded a suspicious session overnight and the SOC
dropped a span-port capture on `pcap01`. Your job is classic triage: establish
how the intruder got in and what they left behind — on the actual victim host.

## Objectives

1. Analyze `/evidence/capture.pcap` — reconstruct what happened.
2. Prove the intruder's access path still works.
3. Locate the persistence payload they staged.

## Suggested flow

- The capture is ground truth. Read every stream, not just the login.
- Cleartext protocols hand out credentials — and humans reuse them.
- Deliverable: write your findings to `/home/analyst/report.txt` — abused account + persistence path.
- The transferred files say where to look on disk.

## Environment

- **Kali**: analysis workstation (Wireshark is on the desktop)
- **pcap01**: the victim host holding the evidence — IR access
  `ssh analyst@<pcap01>` (pw `analysis`), then scp the capture to Kali
