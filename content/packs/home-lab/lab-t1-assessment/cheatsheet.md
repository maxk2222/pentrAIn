# Cheatsheet — Home Field Advantage

## Find your scope

```bash
ip -4 addr show eth1              # WAN lease → your /24
# or check Settings → lan.scope_cidr (empty = auto /24 from lease)
```

## Stage the assessment

```bash
# hosts
sudo arp-scan -l -I eth1
sudo nmap -sn 192.168.X.0/24 -oA discovery

# services per host (script the loop for many hosts)
for h in $(sudo arp-scan -l -I eth1 | awk '/^[0-9]+\./{print $1}'); do
  sudo nmap -sV -sC -oN "scan-$h.txt" "$h"
done

# the usual suspects
nmap -p 80,443,8080,8443,554,5000,1900,5353,9100 <net>/24   # web/rtsp/upnp/ipp
smbclient -L //<nas-ip> -N
snmpwalk -v2c -c public <ip> 2>/dev/null | head
sudo nmap --script vuln <interesting-host>
```

## Report contract (the flag greps this)

`lan-report.md` in `/root` or `/home/kali` must contain:
- at least one **IPv4 address** (your discovered hosts)
- the words **port** or **service**
- **finding** / **risk** / **recommend** / **severity** vocabulary

`cp ~/lan-report-template.md ~/lan-report.md` — fill every table row.
