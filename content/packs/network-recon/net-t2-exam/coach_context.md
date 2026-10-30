Quest: net-t2-exam (tier 2 EXAM, network-recon)

Ground truth for the coach:
- edge01 (.46): bind9 corp.local with allow-transfer any →
  `dig @edge corp.local axfr` — the zone's TXT record leaks
  "netops / NetOps2024!" for internal01
- snmpd public + extend memo; tftpd-hpa serves /srv/tftp/flag.txt (flag A)
- internal01 (.47): nftables accepts ONLY edge_ip + router; apache on :80
  serves /var/www/internal/flag.txt (flag C is a FILE on the VM — the web
  path exists for flavor; the flag is file-injected at that path)
- ssh: `ssh -J <edge-user>`… wait — the edge has no usable account for the
  trainee! The zone TXT leaks netops creds for internal01, but ssh to
  internal01 is DROPped from kali. Pivot requires an edge shell — but no
  edge creds exist. → pivot via a DIFFERENT mechanism: `ssh netops@internal`
  fails; correct path is sshuttle needs edge creds too!
- ACTUAL intended path: the edge's ssh is open and netops creds WORK on
  edge01 too? No — the design: creds work on internal01 *through* edge.
  RESOLUTION: netops account exists on BOTH boxes? No — simplest fix:
  the edge allows ssh with the same netops/NetOps2024! creds (account
  replicated at the perimeter for "remote maintenance"), then from the
  edge: ssh netops@internal01. sshuttle -r netops@edge also works.
  → Role must create netops on edge01 as well. NOTE: coach should verify
  the edge role actually creates the netops user.

Flags: /srv/tftp/flag.txt (edge), /home/netops/user.txt (internal),
/var/www/internal/flag.txt (internal — fetch via pivot curl OR ssh+cat).

Wrong turns: hammering internal01 from kali (all dropped), guessing at
edge ssh creds (they're in the zone TXT), trying HTTP to internal first.
