# Cheatsheet — Juice Shop

## Targets

- **juice01** — OWASP Juice Shop (Node/Express SPA + API) on :3000

## Useful commands

```bash
curl -s http://<juice01>:3000/rest/products/search?q=x | jq .
gobuster dir -u http://<juice01>:3000/ -w common.txt
# score-board leaks the challenge list — your roadmap
curl http://<juice01>:3000/#/score-board
```

## Concepts

- SPA = the API is the attack surface; enumerate /rest/* and /api/*
- JWT weaknesses, BOLA on basket/order ids, file-upload traps
- Challenges solve server-side via tracking pixels — e.g. the admin page
  loads `/assets/public/images/padding/19px.png`; requesting it with a
  `referer` header flips the challenge (fragments like /#/administration
  never reach the server!)
- Solve banners trigger instantly — watch for the notification
