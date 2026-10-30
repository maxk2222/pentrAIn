# Defense notes — Pressing Matters

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Weak admin password | `passw0rd` falls to a small wordlist | Strong unique password + 2FA plugin; SSO if available |
| `admin` as the login name | User enumeration is instant (`?author=1`, REST API) | Non-obvious admin name; block author archives + `/wp-json/wp/v2/users` for anonymous |
| Theme/plugin file editor enabled | wp-admin → arbitrary PHP → RCE | `define('DISALLOW_FILE_EDIT', true);` in wp-config.php |
| World-readable uploads dir | Sensitive files in the media library leak | Serve uploads with tight ACLs; never store secrets as media |
| No rate limiting on wp-login/xmlrpc | Online brute force unthrottled | Fail2ban on wp-login + disable/limit xmlrpc |

## Audit commands

```bash
# what's exposed anonymously?
curl -s http://<host>/wp-json/wp/v2/users | head     # usernames leak here
curl -s "http://<host>/?author=1" -o /dev/null -w '%{redirect_url}'

# editor disabled?
grep -n DISALLOW_FILE_EDIT /var/www/html/wp-config.php

# weak-password sweep (run against your own install)
wpscan --url http://<host> -U <users> -P top-1000.txt --password-attack wp-login
```

## Detection

- POST /wp-login.php bursts from single IPs (fail2ban signature)
- wp theme/plugin file edits: audit log plugin or inotify on wp-content/themes
- outbound connections from the apache/wordpress process (webshell C2 shape)

## Further reading

- WordPress hardening guide (DISALLOW_FILE_EDIT, security keys, xmlrpc)
- OWASP WSTG — CMS testing section
