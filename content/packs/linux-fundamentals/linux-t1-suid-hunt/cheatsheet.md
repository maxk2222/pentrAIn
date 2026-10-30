# Cheatsheet — Sticky Bits

## Targets

- **suid01** — SSH server; an onboarding VM with things left lying around

## Useful commands

```bash
# loot first — readable files that mention creds
grep -rIlnE 'passw|cred|login' /opt /etc /srv 2>/dev/null

ssh <user>@<ip>

# SUID/SGID enumeration
find / -perm -4000 -type f 2>/dev/null
find / -perm -u=s -type f 2>/dev/null
ls -l <binary>                            # spot the 's' in owner perms
getcap -r / 2>/dev/null                   # capabilities — the quieter sibling

# GTFOBins file-read pattern (works for base64 and friends)
<bin> /root/root.txt
```

## Concepts

- SUID bit = process runs with the *file owner's* rights, not yours
- `find -perm -4000` is the recon; GTFOBins is the exploitation cookbook
- File-read primitives (base64, cp, cat variants) beat needing a root shell
