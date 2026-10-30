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
