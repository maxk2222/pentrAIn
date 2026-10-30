# Cheatsheet — The Pivot

## Targets

- **web01** — first foothold, dual-homed knowledge
- **internal01** — reachable only through web01

## Useful commands

```bash
ip a; ip route                          # on web01 — see the second net
ssh -L 8443:internal01:443 user@<web01> # local forward
ssh -D 1080 user@<web01>; proxychains nmap -sT -Pn <internal01>
sshuttle -r user@<web01> 10.x.10.0/24
```

## Concepts

- The second NIC is the tell — `ip a` on the first shell
- SOCKS (`-D`) + proxychains covers everything; `-L` is surgical
- Scan through pivots slowly — SOCKS latency fakes filtered ports
