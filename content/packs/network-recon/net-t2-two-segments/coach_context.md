# Coach context — Behind the Firewall

## Intended path

1. `nmap -sV <edge01>` → 22+80. `nmap <internal01>` → all filtered/dropped.
2. `curl http://<edge01>/` → "status ok"; `gobuster dir -u http://edge01/ -w
   <wl>` or guessing → `/config.php` → contains BOTH credential sets:
   `deploy / deploy123` (edge01 maintenance) and `internal_svc / L3tM3In!`
   (internal service account).
3. `ssh deploy@<edge01>` → `edge-flag` at `/home/deploy/flag.txt`.
4. Pivot: `ssh -J deploy@<edge01> internal_svc@<internal01>` (or
   `ssh deploy@edge01` then `ssh internal_svc@internal01` from inside;
   sshuttle also works) → `internal-flag` at `/home/internal_svc/flag.txt`.

## Key facts (stage 2–3 only)

- Cred pairs: `deploy/deploy123` (edge01), `internal_svc/L3tM3In!` (internal01).
- internal01's nftables allows ONLY edge01's ip_last_octet — everything else
  REJECTs, so it doesn't even look down (that's the teaching moment).
- internal01's address: same VLAN, last octet 22.

## Common wrong turns

- Trying `nmap -Pn`/UDP scans on internal01 — it's not stealth, it's policy.
- Port-knocking fantasies — no knock daemon; the path is through edge01.
- `sshuttle` without ssh access to edge01 first — pivot needs the jump creds.
