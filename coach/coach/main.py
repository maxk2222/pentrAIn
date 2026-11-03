"""Coach service entrypoint: subscribe to backend events, manage SessionCoach instances."""
from __future__ import annotations

import asyncio
import contextlib
import time

import structlog

from .client import BackendClient
from .loop import SessionCoach
from .observer import ObserverService

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
                # stream dropped (or first connect) — events may have been
                # missed; attach to any live session we don't know yet
                # (an idle session emits nothing, so without this sweep it
                # would stay un-coached forever after a service restart)
                try:
                    for s in await self.client.active_sessions():
                        await self._ensure_coach(int(s["id"]))
                except Exception as e:
                    await log.awarning("active-session sweep failed", error=str(e))
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
            # cleanup when session ends or resets — a surviving coach would
            # carry the old run's facts/plan/lessons into the fresh attempt
            if topic.startswith("session.") and data.get("state") in (
                    "solved", "aborted", "failed", "resetting"):
                await asyncio.sleep(2)
                await self._drop(sid)

    async def _drop(self, sid: int) -> None:
        coach = self.coaches.pop(sid, None)
        if coach:
            with contextlib.suppress(Exception):
                await coach.stop()
            await log.ainfo("coach detached", session=sid)


async def _task_watchdog() -> None:
    """Dump every asyncio task's stack every 5 min — thread-level
    faulthandler only shows an idle eventloop's select(), hiding the actual
    wedged await."""
    while True:
        await asyncio.sleep(300)
        tasks = [t for t in asyncio.all_tasks() if not t.done()]
        await log.ainfo("task watchdog", alive=len(tasks))
        for t in tasks:
            await log.ainfo(
                "task stack", task=t.get_name(),
                stack=" | ".join(
                    f"{f.f_code.co_name}:{f.f_lineno}"
                    for f in t.get_stack(limit=6)))


async def amain() -> None:
    asyncio.create_task(_task_watchdog())
    svc = CoachService()
    await svc._config(force=True)
    # observer: own task in the same container — shares the backend client
    # and the cfg getter, tails /traj, tips the live coach and distills
    # stuck→recovery windows into coach_lessons (knowledge's write side)
    obs_task = asyncio.create_task(
        ObserverService(svc.client, svc._config).run())
    try:
        await svc.run()
    finally:
        obs_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await obs_task


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
