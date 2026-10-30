Quest: net-t3-exam (tier 3 EXAM, network-recon)

Ground truth for the coach:
- edge01 (.55): bind9 corp.local AXFR open (zone names dmz+vault and their
  docs path); snmpd public + extend edge-creds → edgeop / Edge2024! →
  ssh edgeop@edge (flag A /home/edgeop/user.txt)
- dmz01 (.56, directly reachable): apache /docs/netplan.txt leaks
  vaultop/Vault2024! AND docmaster/Docs2024!; flag B at
  /var/www/html/docs/flag.txt (curl it)
- vault01 (.57): nftables accepts ONLY dmz + router →
  ssh -J docmaster@dmz vaultop@vault → sudo (full sudoer) → /root/vault.txt

This is an EXAM — coach at the stage level:
- The lesson is the chain: protocol enum → foothold → public loot → pivot.
- Redirect specifics to net-t2-dns-enum (axfr/snmp) and
  net-t2-two-segments / linux-t3-pivot (pivot mechanics).

Wrong turns: attacking vault from kali (dropped by nftables), missing the
'extend' output in snmpwalk (it's below the system tree — walk the whole
tree), forgetting -J needs the DMZ account not the vault creds in the
jump position.
