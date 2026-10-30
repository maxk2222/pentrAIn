# Cheatsheet — Juice Shop

## Targets

- **web01** — OWASP Juice Shop (Node/Express SPA + API)

## Useful commands

```bash
curl -s http://<web01>:3000/rest/products/search?q=x | jq .
gobuster dir -u http://<web01>:3000/ -w common.txt
# score-board leaks the challenge list — your roadmap
curl http://<web01>:3000/#/score-board
```

## Concepts

- SPA = the API is the attack surface; enumerate /rest/* and /api/*
- JWT weaknesses, BOLA on basket/order ids, file-upload traps
- Solve banners trigger instantly — watch for the notification
