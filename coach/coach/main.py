"""Coach service entrypoint: subscribe to backend events, manage SessionCoach instances."""
from __future__ import annotations

import asyncio
import contextlib
import time

import structlog

from .client import BackendClient
from .loop import SessionCoach

log = structlog.get_logger(__name__)


class CoachService:
    def __init__(self) -> None:
        self.client = BackendClient()
        self.cfg: dict = {}
        self.coaches: dict[int, SessionCoach] = {}
        self._cfg_ts = 0.0
        # shared daily LLM-token accounting across all SessionCoaches
        self.usage: dict = {"day": "", "tokens": 0}

    async def _config(self, *, force: bool = False) -> dict:
        # refresh settings every 5 min or on demand
        if force or time.time() - self._cfg_ts > 300:
            cfg = await self.client.config()
            if cfg:
                self.cfg = cfg
                self._cfg_ts = time.time()
        return self.cfg

    async def _ensure_coach(self, session_id: int) -> SessionCoach | None:
        coach = self.coaches.get(session_id)
        if coach:
            return coach
        await self._config()
        c = SessionCoach(session_id, self.client, self.cfg, usage=self.usage)
        try:
            if not await c.start():
                await c.stop()
                return None  # terminal session — nothing to coach
        except Exception as e:
            await log.aexception("coach attach failed", session=session_id, error=str(e))
            with contextlib.suppress(Exception):
                await c.stop()  # don't leak a half-started run task
            return None
        self.coaches[session_id] = c
        return c

    async def run(self) -> None:
        async for ev in self.client.events():
            # periodic config refresh → propagate to every live coach
            if time.time() - self._cfg_ts > 300:
                await self._config(force=True)
                for c in list(self.coaches.values()):
                    await c.apply_cfg(self.cfg)
            if ev.get("type") == "_reconnect":
                # stream dropped — events may have been missed; resync all
                for c in list(self.coaches.values()):
                    await c.resync()
                continue
            topic = ev.get("topic", "")
            data = ev.get("data", {}) or {}
            sid = data.get("session_id") or ev.get("session_id")
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                continue  # malformed event — never let it kill the loop
            # learn about new sessions on first event
            coach = await self._ensure_coach(sid)
            if not coach:
                continue
            await coach.feed(ev)
            # cleanup when session ends
            if topic.startswith("session.") and data.get("state") in (
                    "solved", "aborted", "failed"):
                await asyncio.sleep(2)
                await self._drop(sid)

    async def _drop(self, sid: int) -> None:
        coach = self.coaches.pop(sid, None)
        if coach:
            with contextlib.suppress(Exception):
                await coach.stop()
            await log.ainfo("coach detached", session=sid)


async def amain() -> None:
    svc = CoachService()
    await svc._config(force=True)
    await svc.run()


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
