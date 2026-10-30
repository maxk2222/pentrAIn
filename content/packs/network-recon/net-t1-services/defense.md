# Defense notes — The Perimeter

## Vulnerability 1 — Anonymous FTP with readable files

- **Weakness**: vsftpd `anonymous_enable=YES` serving `/srv/ftp`.
- **Detect**: `xferlog` entries for user `anonymous`; `vsftpd.log` shows
  downloads from scanner IPs.
- **Fix**: `anonymous_enable=NO`, remove world-readable files from
  `anon_root`, firewall 21 to known clients.
- **Verify**: `ftp <host>` as anonymous must be refused.

## Vulnerability 2 — Hidden web directory without access control

- **Weakness**: `/backup/` under the docroot, guessable name, no auth.
- **Detect**: access.log shows `GET /backup/` from enumeration tools;
  non-existent-dir probes spike before the hit.
- **Fix**: move backups out of the docroot or require auth; deny dotfile and
  backup paths in the server config.
- **Verify**: `gobuster` no longer finds `/backup` (404/403).

## Vulnerability 3 — MySQL with weak root password, network-exposed

- **Weakness**: `root`/`mysql` accepted, `bind-address` open on the VLAN.
- **Detect**: `general_log`/auth plugin failures; connections from the kali
  range IP; `secrets.creds` SELECT in the slow log.
- **Fix**: strong root password + `ALTER USER ... REQUIRE SSL`; bind to
  localhost; drop the `secrets` table pattern — never store creds in a DB
  reachable with DB creds.
- **Verify**: `mysql -h <ip> -uroot -pmysql` fails; `ss -tlnp` shows 3306 on
  127.0.0.1 only.

## Vulnerability 4 — Reused/stored SSH credentials

- **Weakness**: `dbadm` password sat plaintext in a database table.
- **Detect**: `auth.log` Accepted for dbadm from a scanner IP after DB reads.
- **Fix**: rotate the password, use key auth, audit where creds live
  (`secrets` table deleted).
- **Verify**: ssh password auth for dbadm fails.
