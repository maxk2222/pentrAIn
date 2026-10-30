Quest: web-t1-git-leak (tier 1, web-appsec)

Ground truth for the coach:
- app: apache+php DevPortal in /var/www/html; admin stub at /admin/
- the vuln: /.git/ is fully browseable (apache autoindex) — wget -r -np or
  GitTools/git-dumper recovers the whole repo
- HEAD config.php contains: deploy / D3pl0y!24 (comment says it's reused for
  the deploy user's ssh login — it literally is)
- flag A: /var/www/html/admin/flag.txt — served over HTTP once /admin is found
  (dirb or reading the recovered source reveals the dir)
- flag B: /home/deploy/user.txt — ssh deploy@<ip> D3pl0y!24

Intended path:
gobuster/dirb → /.git/HEAD or listing → wget -r -np /.git/ → cd dump &&
git checkout -- . (or git show) → config.php → ssh deploy@

Common wrong turns:
- curl /config.php — returns empty; PHP executes. Coach should explain WHY
  source disclosure via git is different.
- fetching only .git/HEAD — need the objects; that's what -r/git-dumper is for
- trying the creds only on login.php — the web login is a decoy for the
  real prize: SSH reuse

Style: tier 1 — this is many trainees' first source-disclosure find. Explain
the wget recursion if they're confused; git checkout -- . restores the tree.
