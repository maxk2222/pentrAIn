# Cheatsheet — bash recon building blocks

## Script skeleton

```bash
#!/bin/bash
TARGET=$1
echo "[*] probing $TARGET"
```

Run it: `chmod +x recon.sh && ./recon.sh 10.x.10.20`

## Port probing without nmap

```bash
for p in 21 22 80 443 8080; do
  (echo > /dev/tcp/$TARGET/$p) 2>/dev/null && echo "$p open"
done
```

With nmap: `nmap -p- --min-rate 2000 -oG - $TARGET | grep -oP '\d+/open'`

## Pulling remote files

- `scp user@target:/path/file .` — copy down
- `ssh user@target 'cat /var/log/auth.log' > auth.log` — stream without scp
- `curl -O ftp://target/users.csv` — anonymous ftp
- `curl -s http://target:8080/` — http endpoint

## Counting things (the log-triage idiom)

```bash
# $11 is the source-IP column in sshd failure lines
grep 'Failed password' auth.log \
  | awk '{print $11}' \
  | sort | uniq -c | sort -rn \
  | head -1
```

`awk '{print $N}'` picks columns; `uniq -c` counts; `sort -rn` orders.

## Writing structured output

`echo "$ip" >> /root/attackers.txt` appends a line. Redirect the whole
pipeline with `> file` to overwrite once.
