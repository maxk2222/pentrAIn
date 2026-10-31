Quest: web-t1-sqli-login (tier 1, web-appsec)

Ground truth for the coach:
- apache+php+sqlite on sqli01:80. Two injectable spots:
  - POST / login → `SELECT id,username FROM users WHERE username='$u' AND
    password='$p'` — tautology bypass (`' OR '1'='1' -- ` or sqlmap).
    Success renders /var/lib/portal-data/flag.txt (portal-flag).
  - GET /user.php?u= → `SELECT username,notes FROM users WHERE
    username='$u'` — result rendered →
    `' UNION SELECT username,password FROM users-- ` puts webdev's
    password `D3vBox!24` in the notes cell.
- ssh webdev@sqli01 D3vBox!24 → /home/webdev/user.txt (webdev-flag)
- users: admin/Sup3rAdm!n, guest/guest, webdev/D3vBox!24

Intended path:
recon (two inputs) → login bypass → portal flag → UNION extract →
webdev password → ssh → user flag

Common wrong turns:
- Trying to UNION through the login (it's boolean — no render)
- Column-count mismatch on UNION (lookup has 2 cols: username, notes)
- Forgetting the extracted cred is an SSH password, not a portal account

Style: tier 1 — let them feel the two injection classes: bypass vs
extraction. sqlmap acceptable but encourage one manual payload first.
