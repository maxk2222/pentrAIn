#!/usr/bin/env python3
"""edge proxy for the request-smuggling lab — deliberately naive.

Parses the request HEAD, enforces an ACL on /internal/*, then pipes the raw
socket to the backend. Content-Length is taken literally: `CL: 0` means
"no body" to this proxy — bytes the client appended anyway stream straight
through to the backend as the start of the NEXT request on the shared
connection (0.CL desync). Head-parsed ACL never sees the smuggled line.
"""
import asyncio
import re

BACKEND = ("backend", 5000)
BLOCKED = re.compile(rb"^/internal")


async def _pipe(reader, writer):
    try:
        while data := await reader.read(16384):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(client_r, client_w):
    try:
        head = await asyncio.wait_for(client_r.readuntil(b"\r\n\r\n"), 10)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        client_w.close()
        return
    line = head.split(b"\r\n", 1)[0]
    try:
        path = line.split(b" ", 2)[1]
    except IndexError:
        client_w.close()
        return
    if BLOCKED.match(path):
        client_w.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 12\r\n"
                       b"Connection: close\r\n\r\nedge denied\n")
        await client_w.drain()
        client_w.close()
        return
    back_r, back_w = await asyncio.open_connection(*BACKEND)
    back_w.write(head)
    await back_w.drain()
    await asyncio.gather(_pipe(client_r, back_w), _pipe(back_r, client_w))


async def main():
    server = await asyncio.start_server(_handle, "0.0.0.0", 80)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
