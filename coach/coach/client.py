"""Backend REST + WS client for the coach service (service-token auth)."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog
import websockets

from .config import get_config

log = structlog.get_logger(__name__)


class BackendClient:
    def __init__(self) -> None:
        cfg = get_config()
        self.cfg = cfg
        self._http = httpx.AsyncClient(
            base_url=cfg.backend_url,
            headers={"Authorization": f"Bearer {cfg.coach_service_token}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict) -> Any:
        r = await self._http.post(path, json=body)
        if r.status_code >= 400:
            await log.awarning("backend POST failed", path=path, status=r.status_code,
                               body=r.text[:200])
            return {"error": r.text[:300], "status": "error"}
        try:
            return r.json()
        except Exception:
            return {}

    async def _get(self, path: str) -> Any:
        r = await self._http.get(path)
        if r.status_code >= 400:
            await log.awarning("backend GET failed", path=path, status=r.status_code)
            return {}
        return r.json()

    # config & state
    async def config(self) -> dict:
        return await self._get("/api/coach/config")

    async def active_sessions(self) -> list:
        """Sessions in ready/active state — for the post-restart attach sweep."""
        return await self._get("/api/coach/active-sessions") or []

    async def session_context(self, session_id: int) -> dict:
        return await self._get(f"/api/coach/session/{session_id}/context")

    async def messages(self, session_id: int) -> list[dict]:
        return await self._get(f"/api/coach/messages/{session_id}") or []

    # outputs
    async def send_chat(self, session_id: int, content: str, *, kind: str = "chat",
                        meta: dict | None = None) -> dict:
        return await self._post("/api/coach/message",
                                {"session_id": session_id, "content": content,
                                 "kind": kind, "meta": meta or {}})

    async def stream_draft(self, session_id: int, draft_id: str, content: str,
                           *, reasoning: str = "", done: bool = False,
                           kind: str = "chat") -> None:
        """Relay an in-progress draft to the UI. Fire-and-forget — a dropped
        delta is cosmetic, never worth killing a turn over."""
        try:
            await self._post("/api/coach/stream",
                             {"session_id": session_id, "draft_id": draft_id,
                              "content": content[:4000],
                              "reasoning": reasoning[-4000:], "done": done,
                              "kind": kind})
        except Exception as e:
            await log.adebug("stream relay failed", error=str(e))

    async def suggest_command(self, session_id: int, command: str, why: str) -> dict:
        return await self._post("/api/coach/suggest",
                                {"session_id": session_id, "command": command, "why": why})

    async def exec_in_kali(self, session_id: int, command: str) -> dict:
        return await self._post("/api/coach/exec",
                                {"session_id": session_id, "command": command})

    async def submit_flag(self, session_id: int, value: str) -> dict:
        return await self._post("/api/coach/flag",
                                {"session_id": session_id, "value": value})

    async def check_flag(self, session_id: int, flag_key: str) -> dict:
        return await self._post("/api/coach/flag-check",
                                {"session_id": session_id, "flag_key": flag_key})

    async def mark_checkpoint(self, session_id: int, checkpoint_id: str) -> dict:
        return await self._post("/api/coach/checkpoint",
                                {"session_id": session_id, "checkpoint_id": checkpoint_id})

    async def capture_screen(self, session_id: int) -> dict:
        return await self._post("/api/coach/screen", {"session_id": session_id})

    async def report_llm_usage(self, session_id: int | None, model: str,
                               kind: str, usage: dict | None,
                               latency_ms: int | None) -> dict:
        """Fire-and-forget usage row for the stats page — never blocks a turn."""
        u = usage or {}
        return await self._post("/api/coach/llm-usage", {
            "session_id": session_id, "model": model, "kind": kind,
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
            "latency_ms": int(latency_ms or 0),
        })

    async def update_profile(self, metrics: dict | None = None,
                             track_levels: dict | None = None,
                             xp_total: int | None = None) -> dict:
        body: dict[str, Any] = {}
        if metrics is not None:
            body["metrics"] = metrics
        if track_levels is not None:
            body["track_levels"] = track_levels
        if xp_total is not None:
            body["xp_total"] = xp_total
        return await self._post("/api/coach/profile", body)

    # event stream
    async def events(self) -> AsyncGenerator[dict, None]:
        """Yield events from /ws/coach (all topics). Reconnects on failure —
        yields {"type": "_reconnect"} after every (re)connect so the service
        can resync state that drifted while the stream was down."""
        url = f"{self.cfg.backend_ws_url}?token={self.cfg.coach_service_token}"
        first = True
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, max_size=4 * 1024 * 1024) as ws:
                    await log.ainfo("coach subscribed to event stream",
                                    reconnect=not first)
                    # yield on every connect — including the first: the
                    # service's sweep re-attaches sessions it missed while
                    # down (or never saw, on fresh boot)
                    yield {"type": "_reconnect"}
                    first = False
                    async for raw in ws:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                await log.awarning("event stream dropped, reconnecting", error=str(e))
                await asyncio.sleep(3)
