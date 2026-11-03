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

    async def _post(self, path: str, body: dict, timeout: float = 60.0) -> Any:
        r = await self._http.post(path, json=body, timeout=timeout)
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
                           kind: str = "chat", agent: str = "main") -> None:
        """Relay an in-progress draft to the UI. Fire-and-forget — a dropped
        delta is cosmetic, never worth killing a turn over. `agent` routes
        subagent drafts into their own feed."""
        try:
            await self._post("/api/coach/stream",
                             {"session_id": session_id, "draft_id": draft_id,
                              "content": content[:4000],
                              "reasoning": reasoning[-4000:], "done": done,
                              "kind": kind, "agent": agent})
        except Exception as e:
            await log.adebug("stream relay failed", error=str(e))

    async def send_activity(self, session_id: int, text: str = "",
                            *, active: bool = True, agent: str = "main") -> None:
        """Live 'working on X' indicator — ephemeral like stream_draft; a
        dropped update costs the trainee a status line, never worth a turn.
        `agent` keeps parallel worker indicators apart."""
        try:
            await self._post("/api/coach/activity",
                             {"session_id": session_id, "active": active,
                              "text": text[:200], "agent": agent})
        except Exception as e:
            await log.adebug("activity relay failed", error=str(e))

    async def send_agents(self, session_id: int, agents: list[dict]) -> None:
        """Push the worker roster to the UI's agent chips — sticky snapshot,
        replayed to late subscribers. Fire-and-forget."""
        try:
            await self._post("/api/coach/agents",
                             {"session_id": session_id, "agents": agents})
        except Exception as e:
            await log.adebug("agents relay failed", error=str(e))

    async def suggest_command(self, session_id: int, command: str, why: str) -> dict:
        return await self._post("/api/coach/suggest",
                                {"session_id": session_id, "command": command, "why": why})

    async def exec_in_kali(self, session_id: int, command: str,
                           window: str | None = None) -> dict:
        # the backend blocks up to 60s on the tmux marker plus tmux-setup
        # overhead — a 60s client read race kills legit long-running execs
        # (nmap -sV etc.) right at the finish line. 150s clears it.
        body = {"session_id": session_id, "command": command}
        if window:
            body["window"] = window
        return await self._post("/api/coach/exec", body, timeout=150.0)

    async def type_in_pane(self, session_id: int, text: str,
                           window: str | None = None) -> dict:
        body = {"session_id": session_id, "text": text}
        if window:
            body["window"] = window
        return await self._post("/api/coach/type", body, timeout=30.0)

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

    async def log_action(self, session_id: int, tool: str, args: dict,
                         result: dict, status: str = "ok") -> dict:
        """Audit row for a coach-internal action the backend never saw —
        spawn/collect/kill run coach-side only; without this the roster
        lifecycle is invisible to resync, metrics and debugging."""
        return await self._post("/api/coach/action", {
            "session_id": session_id, "tool": tool[:64],
            "args": args, "result": result, "status": status})

    async def log_denial(self, session_id: int, tool: str, args: dict,
                         reason: str) -> dict:
        """Audit row for a coach-side guard denial — the exec/type endpoints
        only see actions that REACH the backend, so guard denials (foreign
        ip, rewrite loop, budget) must self-report or metrics lose them."""
        return await self.log_action(
            session_id, tool, args, {"reason": reason[:300]},
            status="denied")

    async def create_lesson(self, session_id: int | None, text: str,
                            tags: list, applies: str = "global",
                            confidence: float = 0.5,
                            evidence: dict | None = None) -> dict:
        """Observer-written field note — backend sanitizes + dedupes."""
        return await self._post("/api/coach/lesson", {
            "session_id": session_id, "text": text[:240],
            "tags": list(tags or [])[:8], "applies": applies[:80],
            "confidence": float(confidence),
            "evidence": evidence or {}})

    async def list_lessons(self) -> list:
        """All field notes — the observer's dedupe base."""
        return await self._get("/api/coach/lessons")

    async def lesson_hit(self, lesson_id: int) -> None:
        """Positive-attribution ping for a pushed field note."""
        await self._post(f"/api/coach/lesson/{lesson_id}/hit", {})

    async def observer_hint(self, session_id: int, text: str) -> dict:
        """Live advisory into a running coach — guaranteed-read delivery."""
        return await self._post("/api/coach/observer-hint", {
            "session_id": session_id, "text": text[:400]})

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
