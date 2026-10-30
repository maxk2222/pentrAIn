# Coach context — Three Hops Deep

## Intended path

1. `nmap -sV <dmz01>` → 22+80; app01/data01 drop everything (nftables).
2. `curl http://<dmz01>/` → HTML comment `<!-- maint: ops/ops123 -->` →
   `ssh ops@<dmz01>` → `dmz-flag` at `/home/ops/flag.txt`.
3. `cat ~/notes.txt` on dmz01 → `appadm / AppT13r!` for app01.
   Pivot: `ssh -J ops@<dmz01> appadm@<app01>` or `sshuttle -r ops@<dmz01>
   10.x.10.0/24` → `app-flag` at `/home/appadm/flag.txt`.
4. `cat ~/db-notes.txt` on app01 → `dataadm / D4t4!` for data01 →
   `ssh -J ops@dmz01,appadm@app01 dataadm@<data01>` (stacked jump) →
   `sudo cat /root/flag.txt` → `data-flag` (dataadm has NOPASSWD sudo).

## Key facts (stage 2–3 only)

- Cred chain: `ops/ops123` → `appadm/AppT13r!` → `dataadm/D4t4!`.
- Octets: dmz01 .31, app01 .32, data01 .33 — same /24, firewalls do the
  segmentation. `-J` accepts comma-separated hops:
  `ssh -J ops@10.x.10.31,appadm@10.x.10.32 dataadm@10.x.10.33`.
- data-flag is `/root/flag.txt` — dataadm MUST sudo; a non-sudo read fails.

## Common wrong turns

- Trying to reach app01 directly — its nftables rejects non-dmz sources.
- Forgetting `ssh -J` chains stack; sshuttle to the first hop only covers
  hop 1→2.
- `cat /root/flag.txt` as dataadm → permission denied; `sudo` is required.
