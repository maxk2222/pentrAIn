---
id: web-url-traps
title: Webshell ?c= traps & static-file extension filter bypasses
triggers: [?c=, %2500, %00, webshell, extension filter, Only allows]
---

## Webshell URL traps (?c= param style)

- NEVER append `2>&1` to a `?c=` URL — `&` splits the query, PHP only
  receives `cmd 2>` and returns an EMPTY body while the command "works".
  Stdout comes back anyway; just drop it.
- Same for unquoted `>` in the payload: `?c=echo X > /tmp/f` makes the
  REMOTE shell apply the redirect to the echo — to inject a line that
  itself contains `>`, quote the whole payload:
  `?c=echo "cat /root/root.txt > /out" >> /opt/cron-script.sh`
- `cat` on a file returning EMPTY (with other paths printing fine) is a
  quoting/URL artifact, not missing content — suspect the `&`, not the fs.
- A "shell" on a phantom IP is never worth a second try: if a target IP
  wasn't in tool output, it doesn't exist — re-derive with `ip route` +
  `nmap -sn` instead.

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
