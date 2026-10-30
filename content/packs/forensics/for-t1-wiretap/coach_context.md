Quest: for-t1-wiretap (tier 1, forensics)

Ground truth for the coach:
- evidence: /evidence/capture.pcap (17 packets) + README.txt (incident brief)
- stream 1 (TCP :21): FTP login ops-backup / Restore2024!, RETR of
  maintenance-manifest.txt
- stream 2 (TCP :20→40001): manifest body — names
  /usr/local/lib/systemd-helper/ as the staged-payload dir
- flag A: /home/ops-backup/flag.txt — ssh ops-backup@pcap01 with the same
  password (password reuse is the lesson)
- flag B: /usr/local/lib/systemd-helper/flag.txt — drop path from the manifest;
  also holds systemd-helper.sh (the planted "payload")

Intended path:
tshark -r / wireshark → follow FTP stream → creds → ssh → read manifest's
named path → both flags

Common wrong turns:
- only watching the :21 control stream — the *data* lives on the port-20
  stream; point out FTP's two-channel nature
- dumping the pcap with strings and missing stream context
- forgetting password reuse — creds work on SSH

Style: tier 1 blue-side — the skill is stream reconstruction + turning
network evidence into host triage. Wireshark GUI on Kali is fine; tshark
-f/follow works too.
