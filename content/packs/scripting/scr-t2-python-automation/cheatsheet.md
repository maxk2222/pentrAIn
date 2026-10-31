# Cheatsheet — scripting against HTTP APIs

## requests skeleton

```python
import requests
s = requests.Session()
s.headers.update({"User-Agent": "recon/1.0"})
r = s.get("http://target:8080/api/health", timeout=10)
print(r.status_code, r.json())
```

## Loop-until-success pattern

```python
for candidate in range(10000):
    r = s.post(url, json=payload(candidate), timeout=10)
    if r.ok:
        break
    # non-2xx → inspect r.json() for the reason before retrying
```

## Hashing helpers

```python
import hashlib
digest = hashlib.sha256(data.encode()).hexdigest()
f"{pin:04d}"        # zero-pad numbers to fixed width
```

## Auth headers

```python
s.get(url, headers={"Authorization": f"Bearer {token}"})
```

## Timeouts & resilience

- Always `timeout=` — a hung request stalls the loop forever.
- `r.raise_for_status()` vs checking `r.ok` — choose one, don't mix.
- Save early: `open("/root/loot.txt", "w").write(secret)` the moment you
  have it — don't lose loot to a crash at the end.
