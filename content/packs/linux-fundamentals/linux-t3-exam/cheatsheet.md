# Cheatsheet — Supply Chain

## Targets

- **bastion01** → **app01** → **db01** — three hops, one flag each

## Useful commands

```bash
ssh <user>@<host>                            # read the pre-auth banner
ssh -J <hop-user>@<hop> <user>@<next>        # ProxyJump hop
ssh -J <hop1>,<hop2> <user>@<final>          # multi-hop jump list
sudo -l                                      # check rights on every hop
cat /opt/app/*.yml                           # app configs wire the next tier

# ~/.ssh/config alternative — then plain `ssh <name>`
Host hop1
  HostName <bastion-ip>
  User <hop-user>
Host hop2
  ProxyJump hop1
  User <user>
```

## Concepts

- Each hop's filesystem is recon for the next hop — never stop looting
- -J chains left→right: bastion,app01 means "via bastion then app01"
- nftables drops ≠ unreachable — they mean "come from the right source"
