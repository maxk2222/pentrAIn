# Home Lab — LAN assessment reference

Authorized assessment of **your own network**. Kali sits on the LAN via a
second NIC (net1 → WAN bridge, DHCP) — range isolation does not apply here.

## The five stages

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

# 3 — Access: get on the box, read-only
smbclient -L //<host> -N                    # anonymous share listing
smbclient //<host>/<share> -N -c 'ls'       # walk the file tree
enum4linux -a <host>                        # users, shares, policies
showmount -e <host>                         # NFS exports
snmpwalk -v2c -c public <host> system       # firmware via sysDescr
curl -sI http://<router>                    # router/NAS/cam web UI
ipptool -tv ipp://<printer>/ipp/print /usr/share/cups/ipptool/get-printer-attributes.test
mosquitto_sub -h <host> -t '#' -C 1 -W 5    # open MQTT broker?
avahi-browse -a                             # phones/TVs via mDNS instead

# 4 — Assessment: what's actually weak?
sudo nmap --script vuln <host>
hydra -L users.txt -P passwords.txt ssh://<host>   # only on YOUR boxes

# 5 — Evidence + report
mkdir -p ~/evidence                         # drop listings/dumps here
cp ~/lan-report-template.md ~/lan-report.md # fill every section
```

## Typical home-network findings

- Router/AP web UI on default creds or http-only
- UPnP exposed (igd, `nmap --script upnp-info`)
- Printer exposure (ipp/9100, `nmap -p 515,631,9100`, PJL status banner)
- SMBv1 / anonymous shares on NAS boxes — pull the listing as evidence
- Open MQTT brokers leaking sensor/home data
- Telnet on IoT/cameras; default SNMP `public`/`private`
- Outdated firmware banners (check `-sV` versions against vendor advisories)
- Phones/TVs are usually closed — an mDNS broadcast map is the finding

## Rules of engagement

- Only scan networks you own or have written authorization for.
- Read-only access: listings and banners, never writes or config changes.
- No DoS, no credential brute-force on devices you can't afford to lock out,
  no exploit payloads that leave persistence.
- `Settings → lan.scope_cidr` pins the scope the coach uses; leave it empty
  to auto-derive /24 from the WAN lease.
