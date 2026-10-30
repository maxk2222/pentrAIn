"""Telemetry ingest: batches from the Kali sidecar → DB + live broadcast."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import Session, SessionState, TelemetryEvent
from .events import bus


async def session_by_token(db: AsyncSession, token: str) -> Session | None:
    return (await db.execute(
        select(Session).where(Session.telemetry_token == token)
        .order_by(Session.id.desc()).limit(1))).scalar_one_or_none()


MAX_BATCH = 500          # events per ingest call
MAX_PAYLOAD_BYTES = 65536  # serialized JSON per event


async def ingest(db: AsyncSession, session: Session, events: list[dict]) -> int:
    n = 0
    for ev in events[:MAX_BATCH]:
        kind = str(ev.get("kind", "command"))[:32]
        payload = ev.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)[:1000]}
        try:
            if len(json.dumps(payload)) > MAX_PAYLOAD_BYTES:
                payload = {"truncated": True}
        except (TypeError, ValueError):
            payload = {"unserializable": True}
        db.add(TelemetryEvent(session_id=session.id, kind=kind, payload=payload))
        await bus.publish(f"telemetry.{session.id}", {
            "type": "telemetry", "session_id": session.id, "data": {"kind": kind, "payload": payload}})
        n += 1
    await db.commit()
    return n


async def record_internal(db: AsyncSession, session_id: int, kind: str, payload: dict) -> None:
    """Platform-generated events (flag submits, checkpoints, coach actions)."""
    db.add(TelemetryEvent(session_id=session_id, kind=kind, payload=payload))
    await db.commit()
    await bus.publish(f"telemetry.{session_id}", {
        "type": "telemetry", "session_id": session_id, "data": {"kind": kind, "payload": payload}})


async def recent(db: AsyncSession, session_id: int, limit: int = 200) -> list[TelemetryEvent]:
    return list((await db.execute(
        select(TelemetryEvent).where(TelemetryEvent.session_id == session_id)
        .order_by(TelemetryEvent.id.desc()).limit(limit))).scalars().all())


async def is_alive(db: AsyncSession, session_id: int) -> bool:
    s = await db.get(Session, session_id)
    return bool(s and s.state in (SessionState.READY.value, SessionState.ACTIVE.value))
