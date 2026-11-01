# Cheatsheet — Home Field Advantage

## Find your scope

```bash
ip -4 addr show eth1              # WAN lease → your /24
# or check Settings → lan.scope_cidr (empty = auto /24 from lease)
```

## Discover + enumerate

```bash
sudo arp-scan -l -I eth1
sudo nmap -sn 192.168.X.0/24 -oA discovery

# services per host (script the loop for many hosts)
for h in $(sudo arp-scan -l -I eth1 | awk '/^[0-9]+\./{print $1}'); do
  sudo nmap -sV -sC -oN "scan-$h.txt" "$h"
done

nmap -p 80,443,554,515,631,1900,5353,8123,1883,9100 <net>/24  # web/rtsp/ipp/iot
sudo nmap --script vuln <interesting-host>
```

## Access — read-only probes per device class

```bash
mkdir -p ~/evidence

# NAS / PCs — file tree is the goal
smbclient -L //<ip> -N                          # anonymous share listing
smbclient //<ip>/<share> -N -c 'ls'             # peek inside a share
smbget -R smb://<ip>/<share>                    # pull it into evidence/
enum4linux -a <ip> | tee ~/evidence/enum-<ip>.txt
showmount -e <ip>                               # NFS exports

# routers — config + firmware
curl -sI http://<ip> | tee ~/evidence/http-<ip>.txt
snmpwalk -v2c -c public <ip> system             # sysDescr = firmware
sudo nmap --script upnp-info <ip>

# printers — status, never print
nmap -p 515,631,9100 <ip>
ipptool -tv ipp://<ip> get-printer-attributes.test
printf '@PJL INFO STATUS\n' | nc <ip> 9100

# IoT / cameras / smart home
nc <ip> 23                                      # telnet banner
curl -s rtsp://<ip>:554/ --max-time 5           # camera DESCRIBE
mosquitto_sub -h <ip> -t '#' -C 1 -W 5          # open MQTT?
curl -s http://<ip>:8123/api/                   # Home Assistant auth?

# phones / TVs — confirm closed + what's announced
avahi-browse -a                                 # mDNS: AirPlay, Cast, SMB ads
```

Credentials you legitimately found (docs, configs, the router sticker)?
Trying them is in scope **on your own devices** — lockout-risky brute
force is not.

## Report contract (the flag greps this)

`lan-report.md` in `/root` or `/home/kali` must contain:
- at least one **IPv4 address** (your discovered hosts)
- the words **port** or **service**
- **finding** / **risk** / **recommend** / **severity** vocabulary
- an **access** section — what you reached (shares, configs, banners) or
  what you tried when everything was closed

`cp ~/lan-report-template.md ~/lan-report.md` — fill every table row.
