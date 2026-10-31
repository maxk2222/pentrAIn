# Cheatsheet — The Pivot

## Targets

- **web01** — foothold; web docs leak a shell account
- **db01** — accepts SSH only from web01

## Useful commands

```bash
curl http://<web01>/docs/                    # autoindexed docs
ssh -J <hop-user>@<web01> <db-user>@<db01>   # one-shot ProxyJump
ssh -L 2222:<db01>:22 <hop-user>@<web01>     # local forward
ssh -D 1080 <hop-user>@<web01>; proxychains nmap -sT -Pn <db01>
sshuttle -r <hop-user>@<web01> 10.x.10.0/24
```

## Concepts

- The pivot host is the only machine the target trusts — chain it
- SOCKS (`-D`) + proxychains covers everything; `-J` is the clean one-liner
- Scan through pivots slowly — SOCKS latency fakes filtered ports
