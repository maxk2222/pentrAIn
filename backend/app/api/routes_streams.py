"""WebSocket streams:
- /ws/session/{id}  — frontend multiplex (session state, telemetry, coach msgs, deploy log)
- /ws/coach         — coach service subscription (all events; service-token auth)
- /api/console/{id} — noVNC proxy to the session Kali console
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import secrets
from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_db
from ..models.domain import CoachMessage, Session
from ..services import coach_bridge
from ..services.console import proxy_console, proxy_vm_console
from ..services.events import bus, ephemeral_replay
from ..services.terminal import kali_terminal, user_terminal, wants_for_agent
from .deps import get_current_user, ws_auth

router = APIRouter(tags=["streams"])


async def _pump(ws: WebSocket, topics: list[str],
                replay: Callable[[], list[dict]] | None = None) -> None:
    queues = [await bus.subscribe(t) for t in topics]
    # sticky ephemeral events (mid-turn drafts, live exec output) replayed
    # AFTER subscribing — deltas that raced the snapshot land in the queue
    # and overwrite it, and replayed drafts are cumulative anyway
    if replay:
        for ev in replay():
            await ws.send_json(ev)

    async def forward() -> None:
        while True:
            tasks = {asyncio.create_task(q.get()): q for q in queues}
            done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
            for t in done:
                ev = t.result()
                await ws.send_json(ev)

    async def receive() -> None:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return

    try:
        _done, pending = await asyncio.wait(
            [asyncio.create_task(forward()), asyncio.create_task(receive())],
            return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
    finally:
        for q, t in zip(queues, topics, strict=True):
            await bus.unsubscribe(t, q)


@router.websocket("/ws/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: int,
                     db: AsyncSession = Depends(get_db)):
    if not await ws_auth(websocket, db):
        return
    await websocket.accept()
    await _pump(websocket,
                [f"session.{session_id}", f"telemetry.{session_id}",
                 f"coach.{session_id}"],
                replay=lambda: ephemeral_replay(session_id))


@router.websocket("/ws/coach")
async def coach_ws(websocket: WebSocket):
    """Coach service subscribes here (service token via ?token=)."""
    token = websocket.query_params.get("token")
    if not token or not secrets.compare_digest(token, get_config().coach_service_token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    await _pump(websocket, ["all"])


@router.websocket("/api/console/{session_id}")
async def console_ws(websocket: WebSocket, session_id: int,
                     db: AsyncSession = Depends(get_db)):
    if not await ws_auth(websocket, db):
        return
    await proxy_console(db, websocket, session_id)


@router.websocket("/api/console/vm/{vmid}")
async def console_vm_ws(websocket: WebSocket, vmid: int,
                        db: AsyncSession = Depends(get_db)):
    """Admin console for a standalone VM (template builder)."""
    if not await ws_auth(websocket, db):
        return
    await proxy_vm_console(db, websocket, vmid)


# ---------- browser terminal tabs (kali reverse-channel) ----------

@router.get("/api/terminal/wants/{session_id}")
async def terminal_wants(session_id: int, token: str | None = None,
                         db: AsyncSession = Depends(get_db)):
    """Kali agent polls this (~2s) for channels the UI wants opened.
    Auth: the session's telemetry_token — same credential telemetried uses."""
    wants = await wants_for_agent(db, session_id, token)
    if wants is None:
        return {"chans": {}}
    return wants


@router.websocket("/api/terminal/kali/{session_id}/{chan_id}")
async def terminal_kali_ws(websocket: WebSocket, session_id: int,
                           chan_id: str, db: AsyncSession = Depends(get_db)):
    """Agent-side data socket — outbound dial from kali telemetried."""
    await kali_terminal(db, websocket, session_id, chan_id,
                        websocket.query_params.get("token"))


@router.websocket("/api/terminal/{session_id}/{chan_id}")
async def terminal_user_ws(websocket: WebSocket, session_id: int,
                           chan_id: str, db: AsyncSession = Depends(get_db)):
    """User-side terminal socket — registers the want, then pumps."""
    if not await ws_auth(websocket, db):
        return
    cols = int(websocket.query_params.get("cols") or 120)
    rows = int(websocket.query_params.get("rows") or 32)
    await user_terminal(db, websocket, session_id, chan_id,
                        max(20, min(400, cols)), max(5, min(200, rows)))


# ---------- user-facing chat REST ----------

chat_router = APIRouter(prefix="/api", tags=["chat"])


@chat_router.get("/sessions/{session_id}/chat")
async def chat_history(session_id: int, db: AsyncSession = Depends(get_db),
                       _=Depends(get_current_user)):
    # latest 500 messages, returned in chronological order
    rows = list((await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == session_id)
        .order_by(CoachMessage.id.desc()).limit(500))).scalars().all())
    rows.reverse()
    return [{"id": m.id, "role": m.role, "kind": m.kind, "content": m.content,
             "meta": m.meta, "ts": m.created_at.isoformat() if m.created_at else None}
            for m in rows]


_SLASH_ALIASES = {"/autonomy", "/level", "/mode", "/l"}
_SLASH_SUBS = {"/subagents", "/subs", "/parallel"}
_SLASH_LEVELS = {
    "1": 1, "observer": 1, "spectate": 1,
    "2": 2, "mentor": 2, "advisor": 2,
    "3": 3, "copilot": 3,
    "4": 4, "autonomous": 4, "takeover": 4,
}
_SLASH_USAGE = ("Usage: /autonomy <1-4|observer|mentor|copilot|autonomous> "
                "— switches the coach mode live.")
_SLASH_SUBS_USAGE = ("Usage: /subagents <on|off> — lets the coach spawn "
                     "parallel worker panes (w1-w3) in autonomous mode.")
_SLASH_SUBS_VALS = {"on": True, "1": True, "true": True, "yes": True,
                    "off": False, "0": False, "false": False, "no": False}
_slash_echo_ids = itertools.count(1)


def _slash_echo(msg_id: int | None) -> int:
    """Negative unique id for the UI's user-message echo — a real (positive)
    id would dedupe-block the system reply arriving over the WS, and a fixed
    value would collide on the second slash command."""
    return -(msg_id or (10**9 + next(_slash_echo_ids)))


async def _chat_slash(db: AsyncSession, session_id: int,
                      content: str) -> dict | None:
    """Intercept /autonomy-style commands BEFORE post_message — a stored user
    line would surface in the L4 prompt as an OPERATOR_DIRECTIVE telling the
    model to 'execute /autonomy verbatim'. Returns the response or None when
    the content isn't a command."""
    from ..services import sessions as sessions_svc

    cmd, _, arg = content.partition(" ")
    cmd = cmd.lower()
    if cmd not in _SLASH_ALIASES and cmd not in _SLASH_SUBS:
        return None
    session = await db.get(Session, session_id)
    if cmd in _SLASH_SUBS:
        arg = arg.strip().lower()
        if not arg:
            cur = bool(session and session.subagents_enabled)
            msg = await coach_bridge.post_message(
                db, session_id, "system", "chat",
                f"Subagents: {'on' if cur else 'off'}. " + _SLASH_SUBS_USAGE)
            return {"id": _slash_echo(msg.id)}
        enabled = _SLASH_SUBS_VALS.get(arg)
        if enabled is None:
            msg = await coach_bridge.post_message(
                db, session_id, "system", "chat",
                f"Unknown value {arg!r}. " + _SLASH_SUBS_USAGE)
            return {"id": _slash_echo(msg.id)}
        try:
            await sessions_svc.set_subagents(db, session_id, enabled)
        except sessions_svc.SessionError as e:
            msg = await coach_bridge.post_message(
                db, session_id, "system", "chat",
                f"Subagents unchanged: {e}")
            return {"id": _slash_echo(msg.id)}
        # set_subagents already posted the confirmation + broadcast.
        return {"id": _slash_echo(None)}
    arg = arg.strip().lower()
    if not arg:
        level = session.autonomy_level if session else 0
        msg = await coach_bridge.post_message(
            db, session_id, "system", "chat",
            f"Autonomy level: {level} ({sessions_svc.LEVEL_NAMES.get(level, '?')}). "
            + _SLASH_USAGE)
        return {"id": _slash_echo(msg.id)}
    level = _SLASH_LEVELS.get(arg)
    if level is None:
        msg = await coach_bridge.post_message(
            db, session_id, "system", "chat", f"Unknown level {arg!r}. " + _SLASH_USAGE)
        return {"id": _slash_echo(msg.id)}
    try:
        await sessions_svc.set_autonomy(db, session_id, level)
    except sessions_svc.SessionError as e:
        msg = await coach_bridge.post_message(
            db, session_id, "system", "chat", f"Autonomy unchanged: {e}")
        return {"id": _slash_echo(msg.id)}
    # set_autonomy already posted the system confirmation + broadcast.
    return {"id": _slash_echo(None)}


@chat_router.post("/sessions/{session_id}/chat")
async def chat_send(session_id: int, body: dict, db: AsyncSession = Depends(get_db),
                    _=Depends(get_current_user)):
    from fastapi import HTTPException

    if not await db.get(Session, session_id):
        raise HTTPException(404, "session not found")
    content = str(body.get("content") or "").strip()[:8000]
    if not content:
        raise HTTPException(422, "empty message")
    if content.startswith("/"):
        handled = await _chat_slash(db, session_id, content)
        if handled is not None:
            return handled
    msg = await coach_bridge.post_message(db, session_id, "user", "chat", content)
    return {"id": msg.id}
