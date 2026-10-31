# Cheatsheet — Three Doors Down

## Targets

- **edge01** → **dmz01** → **vault01** — enum → foothold → pivot → root

## Useful commands

```bash
sudo nmap -sU --top-ports 200 <edge>
snmpwalk -v2c -c public <edge>               # read the WHOLE tree — extends leak
dig @<edge> <zone> axfr                      # zone + TXT records
ssh <user>@<edge>

curl http://<dmz>/<dir>/                     # public docs are public
ssh <user>@<dmz>                             # pivot foothold

ssh -J <user>@<dmz> <user>@<vault>           # multi-hop in one command
sshuttle -r <user>@<dmz> <net>/24
sudo -l && sudo -i
```

## Concepts

- SNMP `extend` runs commands — their output is public enumeration surface
- Trust-boundary pivots: each hop's loot names the next hop's creds
- `-J` composes; on a jump the FIRST hop's creds differ from the last's
