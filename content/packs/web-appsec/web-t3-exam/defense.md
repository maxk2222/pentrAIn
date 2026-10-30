# Defense notes — The Reporting API

## What went wrong

| Issue | Impact | Fix |
|---|---|---|
| Weak HS256 secret | Anyone forges any claim | High-entropy secret from a vault; prefer RS256/ES256 with JWKS |
| IDOR on /users/<id>/export | Any token reads any user's data | Authorize per-object: claims["uid"] must match the path id |
| admin claim trusted from the token | One forged flag → admin | Re-check roles server-side (or scope claims tightly) |
| Debug exec endpoint | Admin → root shell | Delete it in prod; never shell out from request params |
| App runs as root | API RCE = host RCE | Dedicated service user, systemd hardening (ProtectSystem, NoNewPrivileges) |

## Audit commands

```bash
# is your jwt secret crackable?
jwt_tool <token> -C -d /usr/share/wordlists/rockyou.txt
# object-level authz — does the code compare subject to path id?
grep -n 'claims\|uid' app.py | grep -i 'export\|user'
# who does the service run as?
systemctl cat pentrain-api | grep -E 'User=|ExecStart'
journalctl -u pentrain-api | grep -iE 'exec|admin'
```

## Detection

- Requests to /users/*/export where path id ≠ token uid (log both)
- Tokens with admin:true minted outside your issuer (issuer/audience checks)
- Spikes in /api/admin/exec — it shouldn't exist, let alone be called
