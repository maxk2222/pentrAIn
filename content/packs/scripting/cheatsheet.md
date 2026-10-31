# Scripting & Automation — track reference

The whole track is graded on **what your scripts produce** — artifacts are
checked on your Kali (`/root/…`) or on the target. Names and paths in each
briefing are part of the contract.

> Your console user is `kali` — paths under `/root/` need root. Start each
> quest with `sudo -i` (or write scripts via `sudo tee`), then the grader
> sees them exactly where the briefing says.

## Universal patterns

```bash
# bash skeleton
#!/bin/bash
set -euo pipefail
TARGET=$1
```

```python
# python skeleton
import requests, sys
T = sys.argv[1] if len(sys.argv) > 1 else "10.x.10.20"
s = requests.Session()
```

## Tier map

- **T1** — bash glue: loops, `/dev/tcp` probes, `grep`/`awk`/`cut`/`sort`/
  `uniq`, writing structured output files.
- **T2** — python against APIs & data: `requests`, `hashlib`, parsing
  pcaps (`tshark`/`strings`), non-interactive `sshpass`/`paramiko`.
- **T3** — unattended kill chains: webshell upload, command injection,
  `ssh`-through-the-compromised-host pivots, proof artifacts.

## Grader vocabulary

- `test -x file` → script must be executable
- `grep -q 'token' file` → artifact must contain an exact string
- command flags run a shell **on the checked VM** — kali checks see your
  console filesystem, target checks see only the target.
