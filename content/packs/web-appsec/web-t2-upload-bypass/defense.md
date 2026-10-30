# Defense notes — Gallery

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Extension blacklist | `.phtml`/`.phar` execute anyway → RCE | Extension *whitelist* + random stored filenames + content re-validation |
| Trusting `Content-Type` header | Client declares `image/png` for a PHP file | Server-side magic-byte check (`exif_imagetype`/`finfo`) |
| Executable code in web-accessible uploads | Shell reachable at `/uploads/shell.phtml` | Uploads outside docroot or `php_admin_flag engine off` on the dir |
| Group-writable root-run script | www-data edits code that runs as root | Root-owned `0755` files in root-owned dirs; audit group-writables |
| Timer runs a mutable script as root | Privesc on a 60-second cycle | Same fix + systemd `ReadOnlyPaths`/hardening on the unit |

## Audit commands

```bash
# files writable by the web user OUTSIDE intended upload dirs
find / -xdev -group www-data -writable 2>/dev/null

# what executes php in this vhost config?
grep -RnE 'SetHandler|AddType' /etc/apache2/

# scheduled units running editable scripts
systemctl list-timers --all | grep -v ' 0 '
for u in $(systemctl list-timers --all --quiet | awk '{print $NF}'); do
  systemctl cat "$u" 2>/dev/null | grep -oP 'ExecStart=\K\S+'
done
```

## Detection

- web server POSTs with suspicious extensions in upload dirs
- new/unknown files under `/uploads` executed shortly after upload
- auditd watch on `/opt/webapp/healthcheck.sh` writes + on ExecStart spawns

## Further reading

- OWASP File Upload Cheat Sheet
- PortSwigger: File upload vulnerabilities (extension + content-type bypasses)
