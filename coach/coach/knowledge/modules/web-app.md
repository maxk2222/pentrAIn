---
id: web-app
title: Web-app sessions — cookie jar, CSRF, 302-success, LFI methodology
triggers: [csrf, user_token, ?page=, php://filter, form:, login form, login, signin, sign in, password=, Set-Cookie, PHPSESSID, 302, session]
---

## Sessions & logins

- Single-label LAN hosts (portal01, sqli01 — no dot) BREAK `curl -b jar`
  across processes: curl+libpsl silently drops jar cookies, the request
  goes out with NO Cookie header and you re-derive a working login forever.
  Either keep the whole flow in ONE process
  (`curl -sL -c /tmp/jar -b /tmp/jar -d '…' URL` — in-memory cookies follow
  the 302 fine), or skip the jar and send the cookie explicitly:
  `curl -b "PHPSESSID=<sid>" URL`. Diagnostic: `curl -sv -b jar URL`
  shows no `> Cookie:` line when the jar was dropped. Same-session
  `-c jar` writes still work — only cross-process `-b jar` reads lose it.
- Verify the login BEFORE exploiting: fetch a protected page
  (`/index.php`), a 302 back to login means the POST failed.
- Login forms often carry a CSRF token — a silent auth failure (every
  response is a redirect/empty page despite correct creds) usually means a
  missing hidden field. Fetch the form, extract it, POST it along:
  `tok=$(curl -s -c jar LOGIN | grep -oP "user_token' value='\K[^']+")`
  then `-d "username=..&password=..&user_token=$tok&Login=Login"`.
- A POST that returns an EMPTY body is usually a 302 SUCCESS, not a
  failure — the login worked and the page lives behind the redirect.
  Follow it: `curl -sL -c /tmp/jar -b /tmp/jar -d '…' URL` or GET `/`
  with the same jar. Grepping an empty body for the flag is a dead turn.
- Retrying the SAME payload with cosmetic changes (new cookie file,
  added -L, same ../ count) is a loop, not iteration — change exactly
  ONE variable per attempt and keep the rest fixed.

See guide `web-url-traps` for ?c= webshell and static-filter quirks.

## LFI methodology — in this order, never skip the sanity check

1. `?page=../../../../etc/passwd` proves traversal works at all
2. empty page / same page back → ADD more `../` (include() resolves
   relative to the vulnerable script's dir — an endpoint under
   /vulnerabilities/x/ needs 4-6 levels to reach filesystem root)
3. absolute `?page=/absolute/path/file` skips the depth game entirely
4. `php://filter/convert.base64-encode/resource=<file>` when include()
   executes/parses the file instead of printing it
