Quest: web-t2-exam (tier 2 EXAM, web-appsec)

Ground truth for the coach:
- login sqli: SELECT users WHERE username='$u' AND password='$p' on sqlite
  → admin' OR '1'='1' -- bypasses (real account hr-admin exists)
- post-login panel reads /var/lib/intranet/flag.txt (flag A) and links upload.php
- upload.php blacklist: php/php3-7/pht → shell.phtml or shell.phar executes
- /var/www/html/uploads/flag.txt — flag B, grab via http after enum
- /flag.txt at fs root — flag C, webshell `cat /flag.txt` (www-data can read,
  injected 0644)

This is an EXAM — coach at the stage level:
- The chain order is the lesson: enum → bypass → filter evasion → RCE.
  If they skip enum and hit upload.php directly unauthenticated, they'll
  get redirected — nudge back to the login.
- Redirect to web-t2-juice-shop (injection mindset) and
  web-t2-upload-bypass (extension games).

Wrong turns: trying .php5/.pht (both in the blacklist), expecting uploads
to land in /uploads/ under a different vhost, hunting for .htaccess tricks
(not needed — .phtml is already executable).
