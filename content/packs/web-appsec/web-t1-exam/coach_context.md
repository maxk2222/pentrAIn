Quest: web-t1-exam (tier 1 EXAM, web-appsec)

Ground truth for the coach:
- /var/www/portal/.git is web-accessible (apache default serves it)
- git history: v1 config.php leaked deploy / Deploy2024! (ssh creds);
  v2 scrubbed it — `git log -p` or git-dumper reveals it
- login: SELECT users WHERE username='$u' AND password='$p' on sqlite —
  bypass with admin' OR '1'='1' -- (or sqlmap)
- flag A: /var/lib/portal-data/flag.txt — rendered by index.php post-login
- flag B: /home/deploy/user.txt — ssh with the leaked creds

This is an EXAM — coach at the stage level:
- Two independent skills under test: source disclosure AND injection.
  If they brute-force the login panel, ask what else the webroot serves.
- Redirect specifics to web-t1-git-leak (repo reconstruction) and
  web-t1-sqli-login (sql injection) — techniques identical.

Wrong turns: sqlmap against the .git endpoint, hydra on the login form
(online brute when the query itself is the bug), downloading .git/HEAD
file-by-file instead of using a dumper.
