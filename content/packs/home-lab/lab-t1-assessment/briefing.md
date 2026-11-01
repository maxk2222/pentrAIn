# Home Field Advantage

No lab targets this time. Your Kali gets a second NIC on the real LAN —
**your** network is the assessment scope.

## Task

Run a full internal pentest-style assessment of your home network and
deliver a written report:

1. **Discover** every live host on the LAN.
2. **Enumerate** services, versions and OS guesses per host.
3. **Access** — actually probe the devices, read-only: list shares, read
   configs/banners, walk the file tree where a service allows it. Routers,
   NAS, printers, PCs, phones, TVs, IoT — every device class gets its own
   probe set (see the cheatsheet). Save anything you pull to
   `~/evidence/` — a directory listing or a config dump beats a port list.
4. **Report** — write `lan-report.md` on Kali covering hosts, open
   ports/services, what you could access, and findings with severities.
   The report flag is the only flag — the write-up IS the deliverable.

## Scope

- Scope = the subnet configured in **Settings → `lan.scope_cidr`**, or the
  /24 of your Kali's WAN lease when the setting is empty.
- Only touch devices inside that scope — these are real machines, not lab
  VMs. Read-only probes only: no writes, no config changes, no DoS, and no
  credential brute force on gear you can't afford to factory-reset.
  Passwords are fair game ONLY on devices you own and can reset.
- "Nothing accessible" is a legitimate result — document what you tried;
  an airtight LAN is a finding too.
- Internet access comes with the uplink — `apt`, `pip`, `curl` work.

## Environment

- `kali` — your console + second NIC (eth1) on the LAN. `wifi` toggle in
  the session bar shows the uplink state.
- `~/lan-report-template.md` — skeleton with the sections the flag greps.
- `~/evidence/` — drop share listings, config dumps and banners here;
  reference them from the report.

> Note: the uplink needs a DHCP server on the LAN (any normal router).
