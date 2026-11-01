# Defense — home network hardening checklist

If the assessment turned up findings, here's the fix list:

## Router / access point
- Change the admin password; disable remote management; enforce WPA2/WPA3.
- Disable UPnP (igd) — it's the single most-abused service on home gear.
- Check for firmware updates; enable auto-update if offered.
- Guest network for IoT + visitors — keep your LAN for your own devices.

## Devices
- Kill telnet and ftp anywhere they still live; use ssh/sftp.
- SNMP: change `public`/`private` communities, or disable entirely.
- Printers: disable IPP/9100 if unused; require auth for the web UI.
- NAS/shares: no anonymous write; SMBv1 off; per-user ACLs.

## Detection going forward
- Router/DHCP client list — know every MAC that should be there.
- Periodic `arp-scan`/`nmap -sn` sweep against your own baseline; new
  devices are the earliest warning sign.
- Router logs + DNS query logs if the box supports them.
