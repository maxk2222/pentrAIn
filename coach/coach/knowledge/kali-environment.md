# Kali lab environment — field notes

Facts observed on the session Kali boxes. Trust this over generic memory.

## Installed tooling

Provisioned by the `pentrain_kali_agent` role (KALI_TOOLS in context lists
the live probe — anything absent there is NOT installed, don't retry it):

- recon: nmap, masscan, netdiscover, arp-scan, whatweb
- web: gobuster, ffuf, nikto, sqlmap, wpscan, curl, wget, jq
- services: smbclient, enum4linux-ng, rpcclient, ldapsearch, ftp, nc,
  socat, mysql (mariadb), psql, redis-cli, sqlite3
- creds/exploit: hydra, john, hashcat, medusa, msfconsole, evil-winrm
- pivot/remote: ssh, sshpass, expect, sshuttle, proxychains4, xfreerdp3
- files/forensics: python3 (pexpect), tcpdump, tshark, binwalk, exiftool
- wordlists: /usr/share/wordlists/ (rockyou.txt.gz → gunzip first,
  dirb/dirbuster lists under /usr/share/wordlists/dirb/)

## Range topology

- Targets live on an isolated /24 behind the range router (.254) — the
  router is infrastructure, never a target.
- No internet in the range: apt/pip/curl outbound all fail unless the
  session line says INTERNET: YES.
- Hostnames resolve via /etc/hosts pins: `getent hosts <name>` → real IP.

## Shell quirks that have bitten

- The pane runs zsh: `!` inside DOUBLE quotes triggers history expansion
  ("event not found"). Single-quote payloads or drop the shebang and run
  `sh script.sh`.
- `ssh host 'cmd'` has NO TTY — remote pagers (journalctl, less, man) and
  vim dump-and-exit instead of opening. Use `ssh -tt` when a sudo-NOPASSWD
  privesc needs a pager escape (`!/bin/sh`) or an editor (`:!/bin/sh`).
- A remote password prompt typed via type_in_pane is time-critical:
  sshd LoginGraceTime (~120s) kills the connection. Answer immediately,
  never queue other actions first.
- mariadb client ≠ mysql client: `mysql --skip-ssl` (not `--ssl-mode=
  DISABLED`) when the server doesn't do TLS; `-h <ip> -u user -p<pass>`
  with no space before the password.
- Non-interactive beats interactive: `smbclient -N -L //host/` and
  `smbclient //host/share -U user%pass -c 'get file'` > entering the
  smb> shell; `ftp` reads a heredoc (`ftp -n host <<EOF\nuser anonymous x\nls\nEOF`).
- enum4linux-NG ≠ enum4linux: the NG rewrite dropped `-a` — use `enum4linux-ng -A <ip>`
  (A = all simple checks). Old tutorials still say -a; it errors out.
- Report/deliverable flags: when FLAGS names a file (`*-report.md`, `*.txt`),
  write it EARLY from the evidence you have and refine — don't keep
  re-enumerating a network you already mapped. A template may sit in ~ —
  `ls ~ | grep -i template` before writing from scratch.
- sshpass present → `sshpass -p 'pass' ssh -o StrictHostKeyChecking=no
  user@host 'cmd'` runs remote commands in ONE exec (no interactive pane
  dance). Alternative without sshpass: SSH_ASKPASS trick (see prompt).
- tar wildcard privesc: checkpoint files must land INSIDE the tarred
  directory (`cd /path/spool && touch -- '--checkpoint=1'
  '--checkpoint-action=exec=sh pwn.sh'`), then POLL the output file until
  the cron run produces it — minutely crons need up to ~70s.
- Long tasks: bound every command (`--max-time 30`, `-T4 --max-retries 2`,
  `-w 5`); an unbounded curl/nc wedges the pane and costs a C-c turn.

## Web app work

- Session state lives in ONE cookie jar: `curl -c /tmp/jar -b /tmp/jar`
  on EVERY request — a fresh `-c` file per attempt discards the login you
  just did. Verify the login BEFORE exploiting: fetch a protected page
  (`/index.php`), a 302 back to login means the POST failed.
- Login forms often carry a CSRF token — a silent auth failure (every
  response is a redirect/empty page despite correct creds) usually means a
  missing hidden field. Fetch the form, extract it, POST it along:
  `tok=$(curl -s -c jar LOGIN | grep -oP "user_token' value='\K[^']+")`
  then `-d "username=..&password=..&user_token=$tok&Login=Login"`.
- LFI methodology — in this order, never skip the sanity check:
  1. `?page=../../../../etc/passwd` proves traversal works at all
  2. empty page / same page back → ADD more `../` (include() resolves
     relative to the vulnerable script's dir — an endpoint under
     /vulnerabilities/x/ needs 4-6 levels to reach filesystem root)
  3. absolute `?page=/absolute/path/file` skips the depth game entirely
  4. `php://filter/convert.base64-encode/resource=<file>` when include()
     executes/parses the file instead of printing it
- Retrying the SAME payload with cosmetic changes (new cookie file,
  added -L, same ../ count) is a loop, not iteration — change exactly
  ONE variable per attempt and keep the rest fixed.
