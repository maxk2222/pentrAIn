# Defense notes — Committed

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| `.git/` inside the document root | Full source + history disclosure (CWE-527) | Deploy build artifacts, not the repo; deny `\.(git|svn|hg|env)` in the vhost |
| Autoindex enabled | `.git` browsable — trivial recursive download | `Options -Indexes` on production vhosts |
| Secrets committed to git | Password in `config.php` survives in history forever | Secrets via env/secret-store; rotate + `git filter-repo`/BFG to scrub history |
| Password reuse (app cred = SSH cred) | Web leak → host compromise | Distinct credentials per purpose; key-only SSH |
| No deploy pipeline | "copy the directory" deployments ship everything | CI artifact with an explicit include-list, not an exclude-list |

## Audit commands

```bash
# is anything repo-ish reachable?
for d in .git .svn .hg .env .DS_Store; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' "http://<host>/$d/config"); echo "$d → $code"
done

# apache autoindex check
apache2ctl -S; grep -R 'Indexes' /etc/apache2/

# secret sweep before deploy
git ls-files | xargs grep -nEI 'passw|secret|token|BEGIN.*PRIVATE' 
```

## Detection

- access.log bursts of `GET /.git/` — recursive fetches are loud
- rate alerting on sequential object-file requests
- sshd: `deploy` logins from IPs that aren't the deploy pipeline

## Further reading

- CWE-527: Exposure of Version-Control Repository to an Unauthorized Control Sphere
- GitTools (git-dumper) docs on reconstruction from dumped objects
