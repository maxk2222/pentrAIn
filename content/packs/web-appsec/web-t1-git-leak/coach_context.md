Quest: web-t1-git-leak (tier 1, web-appsec)

Ground truth for the coach:
- app: apache+php DevPortal in /var/www/html; admin stub at /admin/
- the vuln: /.git/ is fully browseable (apache autoindex) — wget -r -np or
  GitTools/git-dumper recovers the whole repo
- HEAD's config.php is scrubbed (getenv("DEPLOY_PASS")); commit "wire up db
  config" still holds deploy / D3pl0y!24 — history keeps secrets
- flag A: /var/www/html/admin/flag.txt — /admin/ is behind Apache BasicAuth
  with the same deploy creds → curl -u deploy:D3pl0y!24 …/admin/flag.txt
- flag B: /home/deploy/user.txt — ssh deploy@<ip> D3pl0y!24

Intended path:
gobuster/dirb → /.git/HEAD or listing → wget -r -np /.git/ → cd dump &&
git checkout -- . (or git log -p / git show) → the scrub commit's parent
has config.php with the creds → ssh deploy@ AND curl -u …/admin/flag.txt

Common wrong turns:
- curl /config.php — returns empty; PHP executes. Coach should explain WHY
  source disclosure via git is different.
- fetching only .git/HEAD — need the objects; that's what -r/git-dumper is for
- trying the creds only on login.php — the web login is a decoy for the
  real prize: SSH reuse

Style: tier 1 — this is many trainees' first source-disclosure find. Explain
the wget recursion if they're confused; git checkout -- . restores the tree.
