# Nordmarkt Feinkost — Defense

Full attack-path documentation: every weakness in the chain, why it worked,
and the remediation Nordmarkt needs.

## Attack path

1. **Recon** — `shop01` answers on 22/80 only. Everything else on the box is
   containerized on internal bridge nets (172.20.0.0/24 `shopfront`,
   172.20.1.0/24 `shopapp`) — invisible from outside.
2. **Backup exposure** — `robots.txt` disallows `/backups/`; nginx autoindex
   lists `deploy-notes.txt` and `shop-backup.tar.gz`. The tarball holds
   `config.env` with the `deploy` SSH password, the `API_TOKEN`, and the
   internal API address.
3. **Foothold** — `ssh deploy@shop01` → `flag-1`. `~/ops-todo.txt` names the
   order API (`172.20.1.2:8080`) and the DB (`172.20.1.3`) on the app
   bridge; `ip route`/`ss` confirm the docker nets. `deploy` is **not** in
   the docker group — container internals stay off-limits without the API
   path.
4. **API compromise** — `GET http://172.20.1.2:8080/api/export?since=…`
   (Bearer token from `config.env`) builds a shell command from raw query
   params → `;`-injection: `;cat /app/data/flag.txt` gives `flag-2`;
   `;cat /app/config.yml` leaks the `shop_ro` DB creds.
5. **Data tier** — `mariadb -h 172.20.1.3 -u shop_ro -p` → `shop.vault`
   holds the migration note naming `/srv/loot/flag.txt` plus the todo row
   about the FILE-priv leftover; `SHOW GRANTS` confirms `FILE` →
   `SELECT LOAD_FILE('/srv/loot/flag.txt')` reads `flag-3` out of the db
   container through SQL.
6. **Root** — `/etc/cron.d/shop-backup` runs `/opt/shop/backup.sh` as root
   every 2 minutes; the script is `root:deploy` and group-writable. Append
   a payload, wait one cycle → `flag-4` from `/root/flag.txt`.

## Fixes

| Weakness | Fix |
|---|---|
| Backup tarball + autoindex inside the webroot | No backups under the docroot — move to object storage; `autoindex off`; CI scan of served paths |
| Credentials in a downloadable archive | No secrets in artifacts; rotate on exposure; per-service credentials |
| Internal API auth = static bearer token in a leakable file | Short-lived tokens or mTLS; firewall the bridge net even from the host |
| Shell injection in the export endpoint | Drop the shell — argument arrays / parameterized reporting calls |
| `shop_ro` holds the global `FILE` privilege | Least privilege — `SELECT` on the schema only; `secure_file_priv` set to a dedicated dir |
| Secrets archive readable by the db user | `0400`/`0600` perms; don't store secret files inside service containers at all |
| Group-writable root cron script | Root-owned `0755`; any writable input to a root job is a privesc primitive |
| "Everything on one box" | Split tiers across hosts, or at least firewall the host→bridge path — the docker nets only isolate the outside view |

## Why this quest has no hints

`cap-t2-nordmarkt` shares the capstone benchmark contract with
`cap-t3-nordwind`: no hints, no checkpoints, no coach briefing. The
engagement letter is the only input — mapping and solving the chain is the
exercise.
