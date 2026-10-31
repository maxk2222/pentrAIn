# Defense — Trusting Query

## What the app did wrong

- **String interpolation into SQL.** `WHERE username='$u'` hands the
  attacker query syntax. One quote rewrites the predicate entirely.
- **No output encoding of query structure.** The directory lookup renders
  whatever the query returns — `UNION SELECT` borrows the page to exfiltrate
  columns the developer never meant to show.
- **Secrets in the same blast radius.** The users table stored a *shared*
  SSH password in plaintext next to web accounts. One injection read it.

## How to fix it

- Prepared statements / parameterized queries — always. `?` placeholders
  bind data, never syntax.
- Least privilege on the DB user; secrets live in a secret store, not in
  application tables.
- Generic error handling — don't let SQL errors or result shapes teach the
  attacker the schema.

## Detection

- Web logs: `'`, `UNION`, `-- `, `OR 1=1` in request lines.
- WAF rules on `UNION SELECT` and comment terminators catch the naive case;
  encoding tricks still slip — the fix is in the code, not the filter.
