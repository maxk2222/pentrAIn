# Kali lab environment — core field notes

Facts observed on the session Kali boxes. Trust this over generic memory.
Detailed technique recipes (git-leak, web-app, pivoting, minimal-hosts,
nested-rce, wifi-lab, log-parsing, containers, privesc-cron) live in the
GUIDES index below — pull them via lookup_guide("<id>") when the situation
matches; they carry verbatim command snippets that do not fit here.

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
- wordlists: /usr/share/wordlists/ — rockyou.txt is ALREADY unzipped
  (use it directly), seclists/ is present, there is NO dirb/ dir. First
  choice for web content discovery:
  /usr/share/wordlists/seclists/Discovery/Web-Content/common.txt
  (bigger: DirBuster-2007_directory-list-2.3-medium.txt in the same dir).

## Range topology

- Targets live on an isolated /24 behind the range router (.254) — the
  router is infrastructure, never a target.
- No internet in the range: apt/pip/curl outbound all fail unless the
  session line says INTERNET: YES.
- Hostnames resolve via /etc/hosts pins: `getent hosts <name>` → real IP.
- Target VMs are MINIMAL debian — missing tools NEVER appear later;
  `missing:`/`blocked:` facts mark them per host. Fallback recipes are in
  guide `minimal-hosts`.
- `apt install` needs the session INTERNET flag — in an isolated range
  it always 404s. Before begging for net, inventory the box: the crack
  you need usually exists under a different name.

## Shell quirks that have bitten

- The pane runs zsh: `!` inside DOUBLE quotes triggers history expansion
  ("event not found"). Single-quote payloads or drop the shebang and run
  `sh script.sh`.
- `ssh host 'cmd'` has NO TTY — remote pagers (journalctl, less, man) and
  vim dump-and-exit instead of opening. Use `ssh -tt` when a sudo-NOPASSWD
  privesc needs a pager escape (`!/bin/sh`) or an editor (`:!/bin/sh`).
- `sudo` over plain ssh dies with "a terminal is required" — check the
  sudoer context ONCE via `echo 'PASS' | sudo -S -l`, don't retry variants.
- "Sorry, user X is not allowed to execute" = the account is simply not a
  sudoer — that NEVER changes mid-quest. Stop feeding it passwords and
  move the work to where you have rights (usually: pull the artifact to
  Kali, operate there).
- Scoped NOPASSWD sudo (`sudo -l` shows a pinned binary list) matches the
  BINARY sudo execs: `sudo timeout 10 airodump-ng` execs "timeout" →
  denied. Put the wrapper OUTSIDE: `timeout 60 sudo airodump-ng …`.
  Same for pipes/redirects — `sudo tool > /root/x` writes as YOU; use
  `sudo sh -c 'tool > /root/x'` only if sh itself is listed, else write
  to your own dir and sudo-cp is still off-limits — prefer /tmp or your
  home for tool output.
- Probes that can hang (ssh/nc/mysql to unverified hosts) burn a whole
  turn when they block the pane — prefix with `timeout 15`.
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
- Long tasks: bound every command (`--max-time 30`, `-T4 --max-retries 2`,
  `-w 5`); an unbounded curl/nc wedges the pane and costs a C-c turn.

## Credentials & access

- NEVER brute-force a credential you invented: hydra with a guessed or
  leetspeak-mutated password wastes turns and can trip lockouts. Creds
  come ONLY from artifacts literally seen in output (configs, repos,
  notes, hashes you cracked). Missing creds = unfound evidence — hunt
  the artifact, don't fuzz auth.
- A credential belongs to the service where it was found — DEPLOY_PASS
  from config.env is for ssh, NOT mysql/docker. Missing DB/service creds
  live in init.sql, docker-compose.yml, .env files — hunt them down,
  don't stuff known passwords at unrelated services.
- A proven shell is also a forensic tool: before rebuilding an artifact
  offline, check whether proven access already reaches the SAME data on
  the target — `ssh host 'git -C /var/www/app log -p'` beats 40 remote
  object fetches when git exists there.
- `caps:` in FACTS = primitives you already PROVED (root-exec via file,
  mysql FILE priv, valid creds). For every remaining objective check caps
  FIRST — reusing a proven primitive beats deriving a new vector. The
  cron you already hijacked can `docker cp`, `cp /root/*`, or drop
  anything else you still need.

## Enumeration discipline

- A concrete artifact lead (exposed .git/backup/config, leaked file,
  looted creds) outranks widening enumeration — finish exploiting what
  you found before scanning further. Re-scans and re-reads of settled
  files without a new hypothesis are loops, not iteration.
- Host alive (ping/routed) but EVERY port filtered = ACL/firewall tier
  isolation — `blocked: filtered:<ip>@<vant>` facts record this; reach
  the host via a pivot (guide `pivoting`), never by more nmap variants.
- Track where downloaded artifacts land (mirror dirs, /tmp files) —
  `find /tmp -name '.git' -o -name '*.cap' -o -name '*.txt'` recovers a
  lost working dir faster than re-downloading it.

## Agent-side tool discipline

- `check_flag` / `submit_flag` / `update_plan` / `lookup_guide` /
  `record_lesson` are ACTIONS — typing them into the Kali pane returns
  `command not found` and burns a turn.
- `record_lesson` persists one line of YOUR distilled session knowledge
  into FACTS (`lessons:`) — survives restarts and reaches workers. Record
  hard-won facts the moment you learn them: which cred unlocks which
  host, which path a pivot needs, which tool a host lacks.
- A denied action carries the reason in its text — change the thing it
  names (run the script alone, re-read the mutated file) instead of
  retrying the same shape with cosmetic edits.
- `exec_in_kali` output is the only ground truth: submit only flag values
  that literally appeared in output; invented values hard-deny.
