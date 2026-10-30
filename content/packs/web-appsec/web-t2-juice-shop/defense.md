# Defense notes — Juice Shop

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Public `/ftp` directory | Unauthenticated file disclosure (flag, coupons, backups) | Disable directory listing; require authz on every file route |
| Hidden-but-not-protected routes | `/#/administration`, `/#/score-board` reachable client-side | Server-side authz — "hidden" is not a control |
| SQLi on login | `' OR 1=1--` bypasses authentication entirely | Parameterized queries / ORM bindings; never string-concat creds |
| No CSP / insecure headers | Easier XSS + info leaks | Strict CSP, security headers, deny framing |

## Hardening snippets

```ts
// route guard — every admin route checked server-side
app.get('/rest/admin/*', denyIfNotAdmin)

// static dir: serve only an explicit allowlist
app.use('/ftp', serveIndexDisallow, staticAllowList(['easter-egg.md']))
```

```sql
-- parameterized, never concatenated
db.query("SELECT * FROM Users WHERE email = ? AND password = ?", [email, hash])
```

## Detection

- HTTP 200s on `/ftp/*` from unauthenticated clients → alert
- `' OR ` patterns in login payloads → WAF rule
- Admin routes hit by non-admin sessions → authz audit log

## Further reading

- OWASP Juice Shop companion guide: https://pwning.owasp-juice.shop
- OWASP Top 10 A01/A05/A07
