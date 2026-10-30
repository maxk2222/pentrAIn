# Cheatsheet — Services Everywhere

## Targets

- **web01** — five services at once: FTP, HTTP, SSH, MySQL, Redis

## Useful commands

```bash
nmap -sV -sC <web01>                  # the full service map first
ftp <web01>                            # user: anonymous
gobuster dir -u http://<web01>/ -w common.txt
mysql -h <web01> -u root -p            # weak creds pay off
redis-cli -h <web01>                   # check it — but watch the clock
```

## Concepts

- Anonymous FTP drops files → read everything
- A "backup" web dir that robots.txt points at is a gift
- MySQL creds in a `secrets` table → try them on ssh (`dbadm`)
- Not every open port is on the path — one service is a deliberate dead end
