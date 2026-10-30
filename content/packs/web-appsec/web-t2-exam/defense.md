# Defense notes — The Intranet

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Interpolated SQL | One quote owns the login | Prepared statements; ORM parameter binding |
| Extension blacklist | `.phtml` slipped straight through | Allowlist (.pdf/.docx only) + store uploads outside the docroot + `php_admin_flag engine off` on the upload dir |
| Uploads executable | A "document" became a webshell | Serve uploads via a script that streams bytes (never executes) |
| Flag in web-readable dir | Free loot | Secrets never under the docroot |

## Audit commands

```bash
# what extensions does your apache execute?
grep -rn 'FilesMatch\|AddType.*php' /etc/apache2/
# what landed in uploads?
find /var/www/html/uploads -type f | grep -vE '\.(pdf|docx?|xlsx?)$'
# interpolations into SQL
grep -rnE "query\\(\".*\\$_|execute\\(\".*\\$_" /var/www/html/
```

## Detection

- access.log: POST to upload.php with .phtml/.phar/.phpt names
- www-data spawning /bin/sh, nc, or reading outside docroot
- failed-login bursts with quotes in the username field

## Further reading

- OWASP file upload cheat sheet (allowlist, rename, out-of-root storage)
- Why blacklist filtering fails: parser differentials, case, double extensions
