# Coach context — lab-t1-assessment

## Ground truth

- This is an AUTHORIZED assessment of the trainee's own LAN. There are no
  lab targets, no planted flags, no intended exploit chain — the
  deliverable is the written report.
- Kali's WAN nic (eth1) is on the real LAN via DHCP. The scope is the
  `lan.scope_cidr` setting or the /24 of that lease — shown as `lan-scope`
  in TARGETS / SCOPE in your context.
- Flag check (verbatim): lan-report.md in /root or /home/kali, non-empty,
  containing an IPv4 address AND port|service vocabulary AND
  finding|risk|recommend|severity vocabulary AND
  access|share|credential|anonymous|filesystem vocabulary — the report
  must cover access probes even when nothing was reachable.
- Completion: the flag key is `report` — call `check_flag` with key
  "report" once the file is written; it re-runs the grep live.
- SCOPE IS ENFORCED, not just advisory: exec commands carrying a private
  IP outside the authorized CIDR are denied outright. If a probe gets
  "denied: <ip> is no known target" — the IP was wrong or out of scope;
  re-check the scope line and scan output. IPs become allowed the moment
  they appear in tool output, so read `ip addr`/scan results before
  probing.
- Report skeleton at /home/kali/lan-report-template.md (pentrain_home_lab
  role). Trainee must copy → lan-report.md and fill it.
- Evidence convention: dumps go to ~/evidence/ (share listings, config
  exports, banners) and get referenced from the report.

## Coaching stance

- Advisor mode fits: the trainee does the work on real devices. Ask what
  the discovery sweep found before suggesting enumeration; ask what each
  host IS before suggesting access probes.
- The quest wants ACCESS, not just ports: after enumerate, push for the
  read-only probe that fits the device class (below). Even an anonymous
  share listing or an SNMP sysDescr is a real "got on the box" result.
- Real LAN ≠ lab: stress gentle scanning (no -T5, no --script intrusive,
  no vuln scripts on IoT until identified), and that some devices will
  simply not answer.
- If they scan outside SCOPE or run something risky (DoS, brute force on
  unknown gear) — stop them. That's the ROE line in the briefing.
- The flag is grep-level, not semantic — a bare nmap dump CAN pass
  technically. Coach for a real report anyway: hosts table, services,
  access probes with what was reachable, findings with severities,
  recommendations.

## Access playbook per device class (read-only)

- NAS / Windows / Samba: `smbclient -L //IP -N` → `smbclient //IP/share
  -N -c 'ls'` → `smbget -R smb://IP/share` for a pull. `enum4linux -a IP`
  for users/shares/policies. NFS: `showmount -e IP`, mount ro.
- Router / AP: `curl -sI http://IP`, `snmpwalk -v2c -c public IP
  system` (sysDescr = firmware), `nmap --script upnp-info IP`. Web UI =
  finding if on http or default creds — creds only on their own router.
- Printer: `nmap -p 515,631,9100 IP`, `ipptool -tv ipp://IP/ipp/print
  /usr/share/cups/ipptool/get-printer-attributes.test`, `nc IP 9100` and
  send `@PJL INFO STATUS\n` (quit after the banner — never print). Web UI
  usually on :80/:443.
- IoT / cameras / smart gear: telnet/ssh banner grab (`nc IP 23`,
  `ssh -o ConnectTimeout=5 user@IP`), RTSP `curl rtsp://IP:554/` DESCRIBE,
  MQTT anonymous subscribe `mosquitto_sub -h IP -t '#' -C 1 -W 5`,
  Home Assistant API `curl -s http://IP:8123/api/`.
- Phones / TVs / casters: usually closed — that's a finding. Confirm via
  mDNS instead: `avahi-browse -a` shows AirPlay/Google-Cast/Android
  services announcing themselves; open port zero on a phone is the
  GOOD answer.
- Found credentials somewhere (config leak, docs, sticker in the report
  photo)? Trying them on ssh/web is in scope for devices they own.
  Brute force only on gear they can factory-reset — say so explicitly.

## Takeover specifics (L4)

- Prefer ONE-SHOT forms — `smbclient //IP/share -N -c 'ls'`, `curl`, `nc`,
  `snmpwalk` — interactive smbclient/ssh/telnet sessions cost type_in_pane
  round-trips and their internals never reach telemetry. Drop straight to
  the read you want.
- Read `ip -4 addr`/the arp-scan output FIRST — every IP there becomes an
  allowed probe target; invented ones get denied.
- Write the report INCREMENTALLY (`cat >> ~/lan-report.md` blocks), then
  call check_flag("report") — a single flag completes the quest.

## Parallel workers (SUBAGENTS enabled)

- After discovery, PARALLELIZE per-device enumeration instead of walking
  hosts serially: `spawn_agent("enumerate services + safe read-only probes
  on 192.168.3.55 — report open services, versions, access results and
  evidence paths")` per discovered host.
- Workers run exec_in_kali on their own tmux window (w1–w3) — each handles
  its own busy pane; their commands join ALREADY_DONE so the parent sees
  what already ran.
- The parent keeps the ROE: the foreign-IP/scope guard applies to worker
  execs identically, and workers share the session action budget.
- Collect with `collect_agent("w1")` (waits up to ~40s) when a result is
  needed for the next step; `agent_status` for an overview. Reports feed
  the access table + findings — the parent writes them into the report.

## Common wrong turns

- Scanning eth0 (the isolated range net) — it's empty except the router;
  the LAN is on eth1.
- Running arp-scan without sudo → zero results.
- `nmap -sn` misses hosts that filter ICMP — arp-scan -l is L2 and sees
  everything on the segment.
- Stopping at port lists — the quest wants the access step: anonymous
  share listing, SNMP read, web UI poke. Coach toward the probe that
  matches the device class.
- smbclient/ssh/telnet run interactively — commands typed inside those
  sessions don't appear in telemetry, so watch for the entry command
  (cp-access) and ASK what they saw inside.
- Writing the report at the END after an hour of scans — encourage notes
  into lan-report.md as they go (checkpoint cp-report fires on the
  filename appearing in any command); drops to ~/evidence as they probe.
- Forgetting UPnP/printers/IoT — home networks hide their worst sins
  there.
- Expecting devices to be friendly — a locked-down LAN is a good result;
  "no access, here's what I tried" fills the same report section.
