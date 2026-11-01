# Home Field Advantage

No lab targets this time. Your Kali gets a second NIC on the real LAN —
**your** network is the assessment scope.

## Task

Run a full internal pentest-style assessment of your home network and
deliver a written report:

1. **Discover** every live host on the LAN.
2. **Enumerate** services, versions and OS guesses per host.
3. **Assess** for the classic home-network findings (default creds,
   anonymous shares, UPnP, SNMP, telnet, old firmware).
4. **Report** — write `lan-report.md` on Kali covering hosts, open
   ports/services and findings with severities. The report flag is the
   only flag — the write-up IS the deliverable.

## Scope

- Scope = the subnet configured in **Settings → `lan.scope_cidr`**, or the
  /24 of your Kali's WAN lease when the setting is empty.
- Only touch devices inside that scope — these are real machines, not lab
  VMs. No DoS, no destructive payloads, no lock-out-risk brute force on
  gear you can't afford to reset.
- Internet access comes with the uplink — `apt`, `pip`, `curl` work.

## Environment

- `kali` — your console + second NIC (eth1) on the LAN. `wifi` toggle in
  the session bar shows the uplink state.
- `~/lan-report-template.md` — skeleton with the sections the flag greps.

> Note: the uplink needs a DHCP server on the LAN (any normal router).
