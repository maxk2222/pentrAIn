"""In-process async event bus.

Topics: "telemetry.{sid}", "session.{sid}", "coach.{sid}", "engine", "all".
Subscribers get dict events {"topic","type","session_id","data","ts"}.
Single-process pub/sub — v1 runs one backend replica; Redis is a later scaling step.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        event.setdefault("ts", time.time())
        event.setdefault("topic", topic)
        targets: set[asyncio.Queue] = set()
        async with self._lock:
            parts = topic.split(".")
            candidates = {topic, "all"}
            # wildcard e.g. "telemetry.*" for all sessions
            if len(parts) == 2:
                candidates.add(parts[0] + ".*")
            for key in candidates:
                targets |= self._subs.get(key, set())
        for q in targets:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    async def subscribe(self, topic: str, *, maxsize: int = 1000) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subs.setdefault(topic, set()).add(q)
        return q

    async def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs.get(topic, set()).discard(q)


bus = EventBus()

# ---------- ephemeral replay ----------
# Live-only events (streamed drafts, activity/output ticks) are one-shot — a
# browser reload or page switch mid-turn used to lose them for good. Sticky
# events are kept per session and replayed once to fresh WS subscribers;
# they're cumulative, so replay is idempotent by design.
_ephemeral: dict[int, dict[str, tuple[float, dict]]] = {}
_EPHEMERAL_TTL = 120.0


async def publish_session(session_id: int, etype: str, data: dict,
                          *, sticky: bool = False) -> None:
    """Publish on `session.{id}`. Sticky events replay to late subscribers;
    a non-sticky event of the same type clears the slot (done draft,
    inactive activity)."""
    ev = {"type": etype, "session_id": session_id, "data": data}
    slot = _ephemeral.setdefault(session_id, {})
    if sticky:
        slot[etype] = (time.monotonic(), ev)
    else:
        slot.pop(etype, None)
        if not slot:
            _ephemeral.pop(session_id, None)
    await bus.publish(f"session.{session_id}", ev)


def ephemeral_replay(session_id: int) -> list[dict]:
    """Snapshot of current sticky events, expired entries pruned."""
    now = time.monotonic()
    slot = _ephemeral.get(session_id) or {}
    for k in [k for k, (ts, _e) in slot.items() if now - ts > _EPHEMERAL_TTL]:
        slot.pop(k)
    if not slot:
        _ephemeral.pop(session_id, None)
        return []
    return [ev for _ts, ev in slot.values()]


def ephemeral_clear(session_id: int) -> None:
    _ephemeral.pop(session_id, None)
