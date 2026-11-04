# External engagement reference

## Discovery (in-scope nets only)

```bash
# breadth — fast SYN sweep over the authorized range
sudo masscan <net> -p0-65535 --rate 1000 -oL masscan.txt
# or breadth via rustscan → hand ports to nmap
rustscan -a <net> -- -sV -sC
# host discovery
sudo nmap -sn -PE -PP -PS21,22,80,443,3389 <net>
fping -g <net> 2>/dev/null
```

## Enumeration

```bash
sudo nmap -sV -sC -O -oA nmap/<host> <host>          # standard depth
sudo nmap -sU --top-ports 100 <host>                 # UDP top ports
whatweb <url>; nuclei -u <url> -severity medium,high,critical
enum4linux-ng <ip>; nxc smb <net>
sslscan <host:port>; testssl.sh --quiet <url>
```

## Validation (turn candidates into confirmed findings)

```bash
# banners/defaults — direct proof beats scanner output
curl -skI <url>; openssl s_client -connect <host:443> </dev/null
smbclient -N -L //<ip>/ 2>&1                         # anonymous SMB listing
ssh -o BatchMode=yes <user>@<ip>                     # auth surface probe
ftp <ip>                                             # anonymous FTP check
```

## Bookkeeping (tools, not commands)

- `record_coverage` / `update_coverage` per surface — the ledger is the
  tested/untested truth; check `list_coverage` before re-testing.
- `create_note` for shared context (working creds, endpoint maps).
- `record_finding` per issue: `candidate` on suspicion, `confirmed` only
  with concrete evidence, `rejected` when ruled out.
- `build_report` → write result to `~/engagement-report.md` →
  `check_flag report`.
