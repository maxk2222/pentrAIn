"""WebSocket streams:
- /ws/session/{id}  — frontend multiplex (session state, telemetry, coach msgs, deploy log)
- /ws/coach         — coach service subscription (all events; service-token auth)
- /api/console/{id} — noVNC proxy to the session Kali console
"""
from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import Callable

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_db
from ..models.domain import CoachMessage
from ..services import coach_bridge
from ..services.console import proxy_console, proxy_vm_console
from ..services.events import bus, ephemeral_replay
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


@chat_router.post("/sessions/{session_id}/chat")
async def chat_send(session_id: int, body: dict, db: AsyncSession = Depends(get_db),
                    _=Depends(get_current_user)):
    from fastapi import HTTPException

    from ..models.domain import Session
    if not await db.get(Session, session_id):
        raise HTTPException(404, "session not found")
    content = str(body.get("content") or "").strip()[:8000]
    if not content:
        raise HTTPException(422, "empty message")
    msg = await coach_bridge.post_message(db, session_id, "user", "chat", content)
    return {"id": msg.id}
