# Coach context — lab-t1-assessment

## Ground truth

- This is an AUTHORIZED assessment of the trainee's own LAN. There are no
  lab targets, no planted flags, no intended exploit chain — the deliverable
  is the written report.
- Kali's WAN nic (eth1) is on the real LAN via DHCP. The scope is the
  `lan.scope_cidr` setting or the /24 of that lease — shown as `lan-scope`
  in TARGETS / SCOPE in your context.
- Flag check (verbatim): lan-report.md in /root or /home/kali, non-empty,
  containing an IPv4 address AND port|service vocabulary AND
  finding|risk|recommend|severity vocabulary.
- Report skeleton at /home/kali/lan-report-template.md (pentrain_home_lab
  role). Trainee must copy → lan-report.md and fill it.

## Coaching stance

- Advisor mode fits: the trainee does the work on real devices. Ask what
  the discovery sweep found before suggesting enumeration.
- Real LAN ≠ lab: stress gentle scanning (no -T5, no --script intrusive,
  no vuln scripts on IoT until identified), and that some devices will
  simply not answer.
- If they scan outside SCOPE or run something risky (DoS, brute force on
  unknown gear) — stop them. That's the ROE line in the briefing.
- The flag is grep-level, not semantic — a bare nmap dump CAN pass
  technically. Coach for a real report anyway: hosts table, services,
  findings with severities, recommendations.

## Common wrong turns

- Scanning eth0 (the isolated range net) — it's empty except the router;
  the LAN is on eth1.
- Running arp-scan without sudo → zero results.
- `nmap -sn` misses hosts that filter ICMP — arp-scan -l is L2 and sees
  everything on the segment.
- Writing the report at the END after an hour of scans — encourage notes
  into lan-report.md as they go (checkpoint cp-report fires on the
  filename appearing in any command).
- Forgetting UPnP/printers/IoT — home networks hide their worst sins
  there.
