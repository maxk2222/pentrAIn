Quest: web-t2-upload-bypass (tier 2, web-appsec)

Ground truth for the coach:
- app: /var/www/html — index.php (upload form) + upload.php (handler)
- upload filters: extension blacklist [php, php3-7, pht] — .phtml and .phar
  are NOT blocked; MIME check trusts $_FILES['type'] (client header)
- apache conf adds SetHandler application/x-httpd-php for .phtml/.phar
- webshell: <?php system($_GET['c']); ?> as shell.phtml → /uploads/shell.phtml?c=…
- flag A: /var/www/internal/flag.txt — dir root:www-data 0750, readable ONLY
  from a shell context (not over HTTP, not by other users)
- privesc: /opt/webapp/healthcheck.sh (root:www-data 0775 — group-writable!)
  executes via webapp-health.timer every minute as root → append payload
- flag B: /root/root.txt

Intended path:
upload .phtml with image/* content-type → webshell via /uploads/ →
cat internal flag → find writable-www-data files OR list-timers →
edit healthcheck.sh → wait ≤60s → root

Common wrong turns:
- shell.php.jpg hoping double-extension works — it's not parsed; phtml is
- fuzzing only filename while sending the real MIME — forge the header too
- running linpeas output overload — point at the group-writable file directly:
  `find / -group www-data -writable 2>/dev/null`

Style: tier 2 — this is the canonical upload→shell→root chain (RootMe-shaped).
Let them try variants; the MIME header trick is the second a-ha.
