# Home Lab — LAN assessment reference

Authorized assessment of **your own network**. Kali sits on the LAN via a
second NIC (net1 → WAN bridge, DHCP) — range isolation does not apply here.

## The four stages

```bash
# 1 — Discovery: who is on the LAN?
ip -4 addr show eth1                        # your lease → your /24
sudo arp-scan --localnet --interface=eth1   # fast L2 sweep
sudo nmap -sn 192.168.X.0/24                # ping sweep alternative
sudo nbtscan -r 192.168.X.0/24              # netbios names

# 2 — Enumeration: what runs on each host?
sudo nmap -sV -sC -O <host>                 # services + scripts + OS guess
sudo nmap -p- -T4 <host>                    # full 65k when -sV looks thin
sudo nmap -sU --top-ports 100 <host>        # DNS/SNMP/NTP live on UDP

# 3 — Assessment: what's actually weak?
sudo nmap --script vuln <host>
smbclient -L //<host> -N                    # anonymous share listing
snmpwalk -v2c -c public <host>              # classic community string
hydra -L users.txt -P passwords.txt ssh://<host>   # only on YOUR boxes

# 4 — Report: findings without a write-up don't count
cp ~/lan-report-template.md ~/lan-report.md   # fill every section
```

## Typical home-network findings

- Router/AP web UI on default creds or http-only
- UPnP exposed (igd, `nmap --script upnp-info`)
- Printer exposure (ipp/9100, `nmap -p 515,631,9100`)
- SMBv1 / anonymous shares on NAS boxes
- Telnet on IoT/cameras; default SNMP `public`/`private`
- Outdated firmware banners (check `-sV` versions against vendor advisories)

## Rules of engagement

- Only scan networks you own or have written authorization for.
- No DoS, no credential brute-force on devices you can't afford to lock out,
  no exploit payloads that leave persistence.
- `Settings → lan.scope_cidr` pins the scope the coach uses; leave it empty
  to auto-derive /24 from the WAN lease.
