# Cheatsheet — Webshell

## Targets

- **web01** — compromised web server; SQLi trail in access.log

## Useful commands

```bash
grep -E "UNION|SELECT|upload" /var/log/apache2/access.log | tail -40
ls -la /var/www/html/uploads/
find /var/www -name "*.php" -newermt "2024-03-20"
ls -la /tmp/ | grep -iE "loot|stage|exfil"
```

## Concepts

- SQLi → file write → webshell → the log tells the order
- `GET /uploads/x.php?c=...` lines prove command execution
- Exfil staging dirs in /tmp often survive reboots-less investigations
- The flag file exists — but only readable on the box, not over HTTP
