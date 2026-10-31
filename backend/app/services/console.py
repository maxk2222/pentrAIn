"""Console proxy: bridges frontend WS → engine-PVE vncwebsocket for a session's Kali VM.

Frontend connects: WS /api/console/{session_id}
Backend: vncproxy() on engine PVE → opens wss to vncwebsocket → bidirectional binary pipe.
API token stays server-side; the browser only sees a same-origin WebSocket.
"""
from __future__ import annotations

import asyncio
import contextlib

import structlog
import websockets
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Session, SessionState
from .engine import get_engine

log = structlog.get_logger(__name__)

# session_id -> {"port": ..., "ticket": ...} stashed by issue_console_ticket,
# consumed by proxy_console. The browser needs the same ticket as the RFB
# password that pveproxy expects on the upstream websocket URL.
_pending: dict[int, dict] = {}


async def issue_console_ticket(db: AsyncSession, session_id: int) -> dict:
    """REST step before opening the console WS: mint a PVE VNC ticket."""
    session = await db.get(Session, session_id)
    if not session:
        return {"error": "session not found"}
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"mock": True}
    if not session.kali_vmid:
        return {"error": "kali vm not ready"}
    if session.state not in (SessionState.READY.value, SessionState.ACTIVE.value):
        return {"error": f"session state {session.state}"}
    try:
        vnc = await engine.pve.vncproxy(session.kali_vmid)
    except Exception as e:
        return {"error": f"vncproxy failed: {e}"}
    _pending[session_id] = {"port": str(vnc["port"]), "ticket": vnc["ticket"]}
    while len(_pending) > 64:  # stale tickets from abandoned connects — evict oldest
        _pending.pop(next(iter(_pending)))
    return {"ticket": vnc["ticket"]}


async def proxy_console(db: AsyncSession, ws: WebSocket, session_id: int) -> None:
    session = await db.get(Session, session_id)
    if not session or not session.kali_vmid:
        await ws.close(code=4404)
        return
    engine = await get_engine(db)

    if engine.mode == "mock":
        await ws.accept()
        # Mock console: keep the socket alive; UI shows a placeholder.
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
        except Exception:
            pass
        return

    creds = _pending.pop(session_id, None)
    if not creds:
        # allow direct connect (reconnect without a fresh ticket) — mint one now;
        # the browser's RFB auth will fail if its password differs, so prefer the
        # ticket flow via issue_console_ticket.
        try:
            vnc = await engine.pve.vncproxy(session.kali_vmid)
            creds = {"port": str(vnc["port"]), "ticket": vnc["ticket"]}
        except Exception as e:
            await log.aerror("vncproxy failed", error=str(e))
            await ws.close(code=4500)
            return
    upstream_url = engine.pve.vnc_websocket_url(
        session.kali_vmid, creds["port"], creds["ticket"])

    await ws.accept()
    try:
        async with websockets.connect(
            upstream_url, ssl=engine.pve.ssl_context(),
            additional_headers=engine.pve.auth_headers(),
            subprotocols=["binary"], max_size=16 * 1024 * 1024,
            ping_interval=None,
        ) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        raise asyncio.CancelledError
                    data = msg.get("bytes")
                    if data is None:
                        text = msg.get("text")
                        if text is not None:
                            data = text.encode()
                    if data:
                        await upstream.send(data)

            async def upstream_to_client() -> None:
                async for frame in upstream:
                    if isinstance(frame, bytes):
                        await ws.send_bytes(frame)
                    else:
                        await ws.send_text(frame)

            _done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_upstream()),
                 asyncio.create_task(upstream_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
    except Exception as e:
        await log.awarning("console proxy ended", error=str(e))
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
