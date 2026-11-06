"""Agent exec link — one persistent outbound WS per session's kali.

The rust pentrain-agent on the kali dials /api/agent/kali/{sid}?token=
(telemetry token, same trust path as terminal). Requests are correlated by
id; replies + streamed output route back to waiting futures. Absent agent
→ callers fall back to the QGA path unchanged.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import secrets
import time

import structlog
from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Session

log = structlog.get_logger(__name__)

MIN_AGENT_VER = 1
MAX_PENDING = 64

_ids = itertools.count(1)


class _Link:
    __slots__ = ("opened_at", "pending", "ver", "ws")

    def __init__(self, ws: WebSocket, ver: int) -> None:
        self.ws = ws
        self.ver = ver
        self.opened_at = time.time()
        self.pending: dict[int, asyncio.Future] = {}


_links: dict[int, _Link] = {}


def is_online(session_id: int) -> bool:
    return session_id in _links


async def _session_by_token(db: AsyncSession, session_id: int,
                            token: str | None) -> Session | None:
    if not token:
        return None
    row = await db.get(Session, session_id)
    if not row or not row.telemetry_token:
        return None
    if not secrets.compare_digest(token, row.telemetry_token):
        return None
    return row


async def agent_ws(db: AsyncSession, ws: WebSocket, session_id: int,
                   token: str | None) -> None:
    """Accept loop for the guest-side exec socket."""
    session = await _session_by_token(db, session_id, token)
    if session is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    link: _Link | None = None
    try:
        # hello handshake — agent version gates feature availability
        msg = await asyncio.wait_for(ws.receive_json(), timeout=15)
        ver = int(msg.get("v") or 0) if msg.get("t") == "hello" else 0
        if old := _links.get(session_id):
            with contextlib.suppress(Exception):
                await old.ws.close(code=4000)
            for f in old.pending.values():
                if not f.done():
                    f.set_exception(ConnectionError("agent re-connected"))
        link = _Link(ws, ver)
        _links[session_id] = link
        await log.ainfo("agent connected", session_id=session_id, ver=ver)
        while True:
            m = await ws.receive()
            if m.get("type") == "websocket.disconnect":
                break
            if (text := m.get("text")) is not None:
                _dispatch(session_id, link, text)
    except Exception as e:
        await log.adebug("agent ws ended", session_id=session_id, error=str(e))
    finally:
        if link is not None and _links.get(session_id) is link:
            _links.pop(session_id, None)
            for f in link.pending.values():
                if not f.done():
                    f.set_exception(ConnectionError("agent disconnected"))
            await log.ainfo("agent disconnected", session_id=session_id)


def _dispatch(session_id: int, link: _Link, text: str) -> None:
    import json
    try:
        msg = json.loads(text)
    except ValueError:
        return
    t = msg.get("t")
    if t == "exec_out":
        # live tail → the same coach_activity event the QGA poll loop emits
        from .events import publish_session
        _fut = asyncio.ensure_future(  # noqa: RUF006 — fire-and-forget event
            publish_session(session_id, "coach_activity", {
                "active": True,
                "agent": msg.get("agent") or "main",
                "text": msg.get("label") or "executing",
                "output": str(msg.get("data") or "")[-1500:]}, sticky=True))
        return
    if t != "exec_done":
        return
    fut = link.pending.pop(int(msg.get("id") or 0), None)
    if fut is not None and not fut.done():
        fut.set_result({k: v for k, v in msg.items() if k not in ("t", "id")})


async def request(session_id: int, msg: dict, timeout_s: float = 90.0
                  ) -> dict | None:
    """Send a request frame, await its correlated reply.
    Returns None when no agent is connected → caller uses QGA fallback."""
    link = _links.get(session_id)
    if link is None:
        return None
    if link.ver < MIN_AGENT_VER:
        return {"error": f"agent v{link.ver} < {MIN_AGENT_VER}",
                "unsupported": True}
    if len(link.pending) >= MAX_PENDING:
        return {"error": "agent busy", "status": "error"}
    rid = next(_ids)
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    link.pending[rid] = fut
    try:
        await link.ws.send_json({**msg, "id": rid})
    except Exception as e:
        link.pending.pop(rid, None)
        return {"error": f"agent send: {e}", "status": "error"}
    try:
        return await asyncio.wait_for(fut, timeout=timeout_s)
    except TimeoutError:
        return {"error": "agent timeout", "status": "error"}
    except ConnectionError as e:
        return {"error": str(e), "status": "error"}
    finally:
        link.pending.pop(rid, None)


async def drop_session(session_id: int) -> None:
    link = _links.pop(session_id, None)
    if link is not None:
        with contextlib.suppress(Exception):
            await link.ws.close()
        for f in link.pending.values():
            if not f.done():
                f.set_exception(ConnectionError("session ended"))


_END_STATES = {"aborted", "failed", "solved", "resetting", "queued",
               "deploying"}
_janitor: asyncio.Task | None = None
_janitor_loop: asyncio.AbstractEventLoop | None = None


def start() -> None:
    """Drop agent sockets when their session leaves the live window —
    mirrors terminal.start()'s janitor so a reset range can't answer
    for the next session on a recycled slot."""
    global _janitor, _janitor_loop
    loop = asyncio.get_running_loop()
    if _janitor is not None and _janitor_loop is loop and not _janitor.done():
        return

    async def run() -> None:
        from .events import bus
        q = await bus.subscribe("session.*")
        try:
            while True:
                ev = await q.get()
                sid, data = ev.get("session_id"), ev.get("data") or {}
                if sid and data.get("state") in _END_STATES:
                    await drop_session(sid)
        finally:
            await bus.unsubscribe("session.*", q)

    _janitor_loop = loop
    _janitor = loop.create_task(run())
