#!/usr/bin/env python3
"""backend for the request-smuggling lab — hand-rolled HTTP/1.1 server.

Deliberately faithful to keep-alive semantics: it loops parsing
request-after-request on the SAME connection, trusting Content-Length as
the body boundary. Bytes the edge left queued after a `CL: 0` head are
therefore parsed as the next request — the classic 0.CL desync sink.
"""
import asyncio
import datetime

LOG = "/var/log/requests.log"
FLAG_FILE = "/srv/api/flag.txt"


def _log(method: str, path: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.utcnow().isoformat()} {method} {path}\n")


def _respond(status: str, body: bytes, ctype: bytes = b"application/json"):
    return (f"HTTP/1.1 {status}\r\nContent-Type: ".encode() + ctype +
            f"\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)


def _dispatch(method: str, path: str) -> bytes:
    _log(method, path)
    if method == "GET" and path == "/":
        return _respond("200 OK",
                        b'{"service":"northbridge-backend",'
                        b'"note":"internal endpoints are edge-filtered"}')
    if method == "POST" and path == "/track":
        return _respond("200 OK", b'{"ok":true}')
    if method == "POST" and path == "/internal/report":
        # state-changing internal endpoint — the smuggled hit lands here
        return _respond("200 OK", b'{"reported":true}')
    if method == "GET" and path == "/internal/flag":
        try:
            flag = open(FLAG_FILE).read().strip().encode()
            return _respond("200 OK", b'{"flag":' + flag + b'}')
        except OSError:
            return _respond("503 Service Unavailable",
                            b'{"error":"flag not provisioned"}')
    if path.startswith("/internal/"):
        return _respond("200 OK",
                        b'{"internal":"' + path.encode() + b'"}')
    return _respond("404 Not Found", b'{"error":"not found"}')


async def _read_head(reader) -> tuple[str, str, int] | None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError,
            asyncio.LimitOverrunError):
        return None
    try:
        line, _, rest = head.partition(b"\r\n")
        method, path, _ = line.split(b" ", 2)
        cl = 0
        for h in rest.split(b"\r\n"):
            if h.lower().startswith(b"content-length:"):
                cl = int(h.split(b":", 1)[1].strip() or b"0")
        return method.decode(), path.decode(), cl
    except (ValueError, UnicodeDecodeError):
        return None


async def _handle(reader, writer):
    try:
        while parsed := await _read_head(reader):
            method, path, cl = parsed
            if cl:
                try:
                    await asyncio.wait_for(reader.readexactly(cl), 15)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                    break
            writer.write(_dispatch(method, path))
            await writer.drain()
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(_handle, "0.0.0.0", 5000)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
