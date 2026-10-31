# Cheatsheet — The DMZ

## Targets

- **dmz01** — edge hop, web + ssh
- **app01** — middle hop, accepts dmz01 only
- **data01** — deepest, accepts app01 only

## Useful commands

```bash
ssh -J ops@<dmz01> appadm@<app01>                      # hop 2
ssh -J ops@<dmz01>,appadm@<app01> dataadm@<data01>     # chained jumps
ssh -D 1080 ops@<dmz01>   # SOCKS for scanning through
```

## Concepts

- Each host's firewall names exactly who may talk to it — read the drop rules
- Credential leaks travel the chain: web note → app config → db secrets
- Multi-hop `-J` lists: comma-separated, left to right
