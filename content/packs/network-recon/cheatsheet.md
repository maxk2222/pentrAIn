# Network & recon — reference card

## Scanning

```bash
nmap -sn <net>/24                      # host discovery (ping sweep)
nmap -sV -sC -T4 <ip>                  # service + script scan
nmap -p- --min-rate 2000 <ip>          # all ports, fast
masscan -p1-65535 <ip> --rate 1000
```

## Pivoting — the core skill

```bash
ssh -J user@hop1 user@target           # ProxyJump — zero tools needed
ssh -L 8080:internal:80 user@hop1      # local forward: localhost:8080 → internal:80
ssh -D 1080 user@hop1                  # SOCKS5 → point proxychains at it
sshuttle -r user@hop <net>/24          # poor-man's VPN, TCP over SSH
proxychains nmap -sT -Pn <internal>    # through SOCKS: -sT full-connect, -Pn no ping
```

## Service cheats

- FTP anonymous: `ftp <ip>` user `anonymous`, any password
- SMB: `smbclient -N -L //<ip>/` → `smbclient -N //<ip>/share`
- Redis: `redis-cli -h <ip> info` — unauth? `keys *`
- MySQL: `mysql -h <ip> -u root -p`
- NFS: `showmount -e <ip>`

## Worth remembering

- "filtered" vs "closed": closed = RST, filtered = drop → host may still be up
- A firewall that accepts from one host is a pivot instruction, not a wall
- Source IP after `ssh -J` = the jump host's — that's the whole trick
