Quest: net-t2-exam (tier 2 EXAM, network-recon)

Ground truth for the coach:
- edge01 (.46): bind9 corp.local with allow-transfer any →
  `dig @edge01 corp.local axfr` — the zone's TXT record leaks
  "netops / NetOps2024!" (works on BOTH boxes — replicated perimeter account)
- snmpd community public + extend memo; tftpd-hpa serves /srv/tftp/flag.txt
  (tftp flag — the free one)
- internal01 (.47): nftables accepts ONLY edge_ip + router. netops exists
  here too (same creds) → /home/netops/user.txt; apache :80 serves
  /var/www/html/internal/flag.txt (web flag — fetch via pivot curl or ssh+cat)

Intended path:
dig axfr → TXT creds → tftp flag (free) → ssh netops@edge01 →
ssh netops@internal01 (or `ssh -J netops@edge01 netops@internal01`,
or sshuttle -r netops@edge01 10.x.10.0/24) → user.txt + curl the web flag.

This is an EXAM — coach at the stage level:
- Chain: zone dump → creds → jump host → internal services.
- Redirect to net-t2-dns-enum (AXFR/SNMP/TFTP mechanics) and
  net-t2-two-segments (pivot patterns) if stuck.

Wrong turns: hammering internal01 from kali (all dropped), guessing at
edge ssh creds (they're in the zone TXT), trying HTTP to internal first.
