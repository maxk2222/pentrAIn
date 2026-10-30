# Coach context — The Perimeter

## Intended path

1. `nmap -sV <svc01>` → 21 ftp, 22 ssh, 80 http, 3306 mysql, 6379 redis.
2. `ftp <svc01>` anonymous → `flag.txt` + `welcome.txt` in the anon root →
   **ftp-flag** at `/srv/ftp/flag.txt` — the file content IS the flag.
3. Web: `gobuster dir -u http://<svc01>/ -w <wordlist>` → `/backup/` →
   `backup/flag.txt` → **web-flag**.
4. `mysql -h <svc01> -uroot -pmysql` → `secrets.creds` has
   `dbadm : Summer2024!` → `ssh dbadm@<svc01>` → `cat ~/flag.txt` →
   **dbadm-flag**.
5. Redis (:6379) is a deliberate dead end — `PING` answers `PONG`, no keys.
   Teach: finding an open service that yields nothing is a normal result.

## Key facts (stage 2–3 only)

- mysql root password: `mysql`. secrets table: `SELECT * FROM secrets.creds;`
- dbadm ssh password: `Summer2024!`
- Flag paths: `/srv/ftp/flag.txt`, `/var/www/html/backup/flag.txt`,
  `/home/dbadm/flag.txt`.

## Common wrong turns

- Hammering SSH with hydra first — noisy and pointless before enum.
- Trying to crack the mysql root hash — it's just `mysql`.
- Chasing redis for 20 minutes — it's the lesson: nothing found IS the answer.
