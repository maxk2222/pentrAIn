"""Browser terminal hub: pairs user WebSockets with kali-side agent WebSockets.

The range is inbound-isolated — kali can only reach the backend OUTBOUND
(same path telemetried already uses). So telemetried polls
GET /api/terminal/wants/{sid}, then dials WS /api/terminal/kali/{sid}/{chan}
and bridges it to a local PTY (tmux session for persistence). This module
registers user-side wants, pairs both sockets and pumps bytes.

Frame protocol (both directions): binary frames = raw terminal bytes;
text frames = JSON control (user→kali: {"t":"resize","cols","rows"};
kali→user: {"t":"exit","code"}).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import re
import secrets
import time

import structlog
from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Session, SessionState
from .events import bus

log = structlog.get_logger(__name__)

MAX_TABS = 8
WANT_TTL_S = 120.0
_CHAN_RE = re.compile(r"^[a-z0-9-]{4,40}$")
# states that tear the range down or make the shells meaningless
_END_STATES = {SessionState.ABORTED.value, SessionState.FAILED.value,
               SessionState.SOLVED.value, SessionState.RESETTING.value,
               SessionState.QUEUED.value, SessionState.DEPLOYING.value}


class _Chan:
    __slots__ = ("cols", "rows", "opened_at", "user_ws", "kali_ws")

    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.opened_at = time.time()
        self.user_ws: WebSocket | None = None
        self.kali_ws: WebSocket | None = None


# session_id -> chan -> _Chan
_CHANS: dict[int, dict[str, _Chan]] = {}
_janitor_task: asyncio.Task | None = None
_janitor_loop: asyncio.AbstractEventLoop | None = None


def _wants(session_id: int) -> dict[str, dict]:
    """View for the kali-side wants poll."""
    return {chan: {"cols": c.cols, "rows": c.rows}
            for chan, c in _CHANS.get(session_id, {}).items()
            if c.user_ws is not None}


async def wants_for_agent(db: AsyncSession, session_id: int,
                          token: str | None) -> dict | None:
    """Validate the telemetry token and return open channel wants."""
    session = await _session_by_token(db, session_id, token)
    if session is None:
        return None
    return {"chans": _wants(session_id)}


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


def _user_ready(session: Session | None) -> bool:
    return bool(session and session.kali_vmid and session.state in
                (SessionState.READY.value, SessionState.ACTIVE.value))


async def _status(ws: WebSocket, state: str, detail: str = "") -> None:
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"t": "status", "state": state, "msg": detail}))


async def user_terminal(db: AsyncSession, ws: WebSocket, session_id: int,
                        chan_id: str, cols: int, rows: int) -> None:
    """User side: registers a want, waits for the kali agent, then pumps."""
    session = await db.get(Session, session_id)
    if not _user_ready(session) or not _CHAN_RE.match(chan_id):
        await ws.close(code=4403 if _CHAN_RE.match(chan_id) else 4400)
        return

    chans = _CHANS.setdefault(session_id, {})
    existing = chans.get(chan_id)
    if existing is None:
        if len(chans) >= MAX_TABS:
            await ws.close(code=4429)
            return
        existing = _Chan(cols, rows)
        chans[chan_id] = existing
    else:  # reconnect: adopt latest size, drop stale user socket
        existing.cols, existing.rows = cols, rows
        if existing.user_ws is not None:
            with contextlib.suppress(Exception):
                await existing.user_ws.close(code=4000)
    existing.user_ws = ws
    try:
        await ws.accept()
        await _status(ws, "live" if existing.kali_ws else "waiting")
        # a reconnect may carry new dimensions — tell the live agent side so
        # the PTY (tmux pane) resizes immediately, not just on the next drag
        if existing.kali_ws is not None:
            with contextlib.suppress(Exception):
                await existing.kali_ws.send_text(json.dumps(
                    {"t": "resize", "cols": existing.cols,
                     "rows": existing.rows}))
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None and existing.kali_ws is not None:
                await existing.kali_ws.send_bytes(data)
            elif (text := msg.get("text")) is not None:
                await _forward_control(ws, existing, text)
    except Exception as e:
        await log.adebug("terminal user side ended", error=str(e))
    finally:
        if existing.user_ws is ws:
            existing.user_ws = None
        # user gone -> want gone -> agent kills its side; close kali now
        if existing.kali_ws is not None:
            with contextlib.suppress(Exception):
                await existing.kali_ws.close()
        chans.pop(chan_id, None)
        if not chans:
            _CHANS.pop(session_id, None)


async def _forward_control(user_ws: WebSocket, chan: _Chan, text: str) -> None:
    try:
        ctl = json.loads(text)
    except (ValueError, TypeError):
        return
    if ctl.get("t") == "resize":
        with contextlib.suppress(Exception):
            chan.cols = max(20, min(400, int(ctl.get("cols") or chan.cols)))
            chan.rows = max(5, min(200, int(ctl.get("rows") or chan.rows)))
        if chan.kali_ws is not None:
            with contextlib.suppress(Exception):
                await chan.kali_ws.send_text(json.dumps(
                    {"t": "resize", "cols": chan.cols, "rows": chan.rows}))


async def kali_terminal(db: AsyncSession, ws: WebSocket, session_id: int,
                        chan_id: str, token: str | None) -> None:
    """Agent side: authenticated by the session's telemetry_token."""
    session = await _session_by_token(db, session_id, token)
    if session is None:
        await ws.close(code=4401)
        return
    chan = _CHANS.get(session_id, {}).get(chan_id)
    if chan is None or chan.user_ws is None:
        # agent dialed a channel nobody wants (tab closed mid-dial)
        await ws.close(code=4404)
        return

    if chan.kali_ws is not None:
        with contextlib.suppress(Exception):
            await chan.kali_ws.close(code=4000)
    chan.kali_ws = ws
    await ws.accept()
    await _status(chan.user_ws, "live")

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None and chan.user_ws is not None:
                await chan.user_ws.send_bytes(data)
            elif (text := msg.get("text")) is not None and chan.user_ws is not None:
                # agent control frames ({"t":"exit",...}) pass through to UI
                with contextlib.suppress(Exception):
                    await chan.user_ws.send_text(text)
    except Exception as e:
        await log.adebug("terminal kali side ended", error=str(e))
    finally:
        if chan.kali_ws is ws:
            chan.kali_ws = None
        # want stays registered -> agent re-dials on next poll (tmux -A)
        if chan.user_ws is not None:
            await _status(chan.user_ws, "waiting")


async def drop_session(session_id: int) -> None:
    chans = _CHANS.pop(session_id, {})
    for c in chans.values():
        for w in (c.user_ws, c.kali_ws):
            if w is not None:
                with contextlib.suppress(Exception):
                    await w.close()


def _start_janitor() -> None:
    """One background task per event loop: cleans up channels on session end
    + stale wants. (Tests run one loop per test — a boolean latch would pin
    the task to a dead loop.)"""
    global _janitor_task, _janitor_loop
    loop = asyncio.get_running_loop()
    if (_janitor_task is not None and _janitor_loop is loop
            and not _janitor_task.done()):
        return

    async def run() -> None:
        q = await bus.subscribe("session.*")
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    ev = None
                if ev is not None:
                    sid, data = ev.get("session_id"), ev.get("data") or {}
                    if sid and data.get("state") in _END_STATES:
                        await drop_session(sid)
                # stale wants (socket died without a clean close)
                now = time.time()
                for sid_, chans in list(_CHANS.items()):
                    for chan_id, c in list(chans.items()):
                        if (c.user_ws is None and c.kali_ws is None
                                and now - c.opened_at > WANT_TTL_S):
                            chans.pop(chan_id, None)
                    if not chans:
                        _CHANS.pop(sid_, None)
        finally:
            await bus.unsubscribe("session.*", q)

    _janitor_loop = loop
    _janitor_task = loop.create_task(run())


def start() -> None:
    """Called once at app startup (import side effect free for tests)."""
    _start_janitor()
