---
id: ssrf-lfi
title: SSRF + LFI — server-side fetch and file-read probes
triggers: [url=, fetch, redirect=, file=, page=, ssrf, lfi, etc/passwd]
---

## SSRF — the parameter IS a URL, the server fetches it

- Params named `url|uri|fetch|load|redirect|callback|webhook|image|pdf`
  are the candidates. First proof: point it at something unique —
  `url=http://127.0.0.1/` or `http://localhost` — a different response
  body than the page's own output means server-side fetch.
- Escalate cheaply: `http://127.0.0.1:PORT/` for internal services
  (6379 redis, 3306 mysql banner via `file://`? no — gopher is the
  redis path, rarely worth it), `http://169.254.169.254/latest/meta-data/`
  on cloud targets (AWS metadata — the crown jewel when present).
- Blind SSRF: response never echoes the fetch — prove with timing
  (`url=http://127.0.0.1:22/` hangs vs closed port fast-fails) or an
  out-of-band hit only if a listener exists in scope.

## LFI — the parameter IS a file path

- `?page=../../../../etc/passwd` — count up `../` until `/etc/passwd`
  shows; absolute `?file=/etc/passwd` skips depth entirely.
- `php://filter/convert.base64-encode/resource=<file>` when the file
  gets EXECUTED (PHP pages) instead of printed — decode the base64 for
  the source.
- log-poison → RCE only when an include chain exists (`/proc/self/environ`,
  `/var/log/apache2/access.log` + UA injection); otherwise stay at
  file-read findings — a readable passwd/config IS the finding.
- See `web-app` for the session-jar discipline on authenticated pages.
