# Cheatsheet — Behind the Firewall

## Targets

- **edge01** — SSH + web, reachable; hosts a leaked config with creds
- **internal01** — drops every packet from your IP; accepts only edge01

## Useful commands

```bash
nmap -sV <edge01> <internal01>         # compare what answers
curl -s http://<edge01>/config.php     # the leak
ssh -J deploy@<edge01> internal_svc@<internal01>
sshuttle -r deploy@<edge01> <net>/24
```

## Concepts

- After `ssh -J`, your packets arrive *from edge01* — the firewall accepts
- `ssh -D 1080` + proxychains works when `-J` chains get long
- Web roots leak config files with plaintext creds — always read them
