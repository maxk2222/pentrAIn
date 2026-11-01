# Nordwind Logistics — Defense

Full attack-path documentation: every weakness in the chain, why it worked,
and the remediation Nordwind needs.

## Attack path

1. **Recon** — `web01` answers on 22/80. `app01` and `db01` exist on the same
   /24 (ARP/mDNS visible) but drop all traffic not sourced from the previous
   hop — enforced by nftables, not by luck.
2. **Exposed `.git`** — `http://web01/.git/` is browsable (nginx `autoindex`)
   and fetchable (`wget -r` / git-dumper). `git log -p` on the recovered repo
   shows the "rotate creds" commit *removing* `config.yml` secrets and
   `deploy_id_rsa` — history keeps them forever.
3. **Foothold** — `deploy`'s SSH password sits in the old `config.yml`.
   `ssh deploy@web01` → `flag-1`. `~/notes/internal.txt` names the inventory
   API on `10.x.10.32:8080` (reachable only from web01).
4. **Pivot** — `ssh -J deploy@web01` / `sshuttle -r deploy@web01 …`.
5. **API compromise** — `app01:8080` issues HS256 JWTs. The signing secret is
   the same `APP_SECRET` committed to the portal repo (secret reuse across
   tiers). Forge `{"role":"admin"}` → `/api/v1/admin/diag?host=…` runs
   `ping -c1 <host>` through a shell → `;`-injection gives RCE as `api` →
   `flag-2` + `/srv/api/config.yml` leaks `api_ro` DB creds for `10.x.10.33`.
6. **Data tier** — `mariadb -h db01` from app01 → `ops.users` holds a
   sha512crypt hash for `ops`. Exfiltrate, crack with `john`/`hashcat` +
   `rockyou` → `ssh -J deploy@web01,api@app01 ops@db01` → `flag-3`.
7. **Root** — `ops` is in group `backup`; a root cron runs
   `/opt/backup/backup.sh`, which is group-writable. Append a command, wait
   one cycle → `flag-4` from `/root/flag.txt`.

## Fixes

| Weakness | Fix |
|---|---|
| `.git` shipped in webroot + autoindex | Deploy from a build artifact, never a checkout; deny `location ~ /\.` in nginx; disable `autoindex` |
| Credentials & keys in git history | Never commit secrets; rotate on exposure, purge history; scan repos in CI |
| Password + secret reuse across tiers | Per-service secrets, vault-managed; leaked secrets rotated everywhere |
| Flat trust graph relying on source-IP pinning alone | Real network segmentation (separate subnets + firewall rules), not just host firewall |
| JWT symmetric secret = app secret | Distinct, high-entropy signing keys; short token TTL; `role` claims from server-side state |
| Shell injection in diagnostics endpoint | No shell; argument arrays / fixed allowlist of diagnostic commands |
| Service config with plaintext DB creds | Secret store or env-injected creds with `0600` perms |
| Crackable password policy (`ops` → rockyou hit) | Password policy + banning reused/breached passwords |
| Group-writable root cron script | Root-owned scripts `0755`; writable-input scripts are a privesc primitive |

## Why this quest has no hints

`cap-t3-nordwind` is the capstone benchmark: no hints, no checkpoints, no
coach briefing. The engagement letter is the only input — mapping and solving
the chain is the exercise.
