# Defense notes — The Leaky Portal

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `.git` in the webroot | Full source + history + secrets for anyone | Deploy *artifacts*, not the repo; deny dot-dirs at the webserver |
| Secrets committed then "scrubbed" | History keeps them forever | Rotate on commit; secrets only via env/vault; `git filter-repo` if ever committed |
| String-interpolated SQL | Auth bypass in one quote | Prepared statements — always, no exceptions |
| Credential reuse across services | Web leak → interactive SSH | Separate identities; secrets in code never map to login accounts |

## Audit commands

```bash
curl -sI http://<host>/.git/HEAD            # 200 = leaked
find /var/www -name '.git' -type d
grep -rnE "WHERE.*'\\$|query\\(.*\\$_" /var/www/   # interpolation into SQL
grep -rnE 'pass|secret|key' /var/www --include='*.php'
```

## Detection

- access.log: GETs on /.git/* paths — nobody legitimate fetches those
- login POSTs containing `'`, `--`, `union` — WAF/mod_security ruleset
- auth.log: ssh logins for accounts that should only deploy (no TTY)
