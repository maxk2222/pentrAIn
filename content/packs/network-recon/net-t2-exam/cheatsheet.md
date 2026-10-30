# Cheatsheet — Perimeter Audit

## Targets

- **edge01** — bind9 + snmpd + tftpd-hpa + sshd; the gossip box
- **internal01** — drops all non-edge traffic; holds two flags

## Useful commands

```bash
sudo nmap -sU --top-ports 200 <edge>
dig @<edge> corp.local axfr                    # zone transfer — read the TXT
dig @<edge> internal.corp.local txt +short
snmpwalk -v2c -c public <edge>
tftp <edge> -c get flag.txt

ssh netops@<edge>                              # creds from the TXT record
ssh -J netops@<edge> netops@<internal>         # ProxyJump through the edge
sshuttle -r netops@<edge> <internal-net>/24    # full subnet pivot
curl http://<internal>/internal/flag.txt       # only via pivot
```

## Concepts

- Segmentation is enforced by *source IP* — become an allowed source
- A zone transfer is the whole phonebook; TXT records are the sticky notes
- ssh -J composes cleanly: no extra tooling needed for a two-hop chain
