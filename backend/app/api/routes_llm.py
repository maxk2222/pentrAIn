"""Session-scoped LLM relay for in-range services (AskOps & friends).

Quest VMs already reach this API for telemetry/flags (testing-mode allow
list + pinned api-host route). An inference-enabled quest VM POSTs here
with the session's telemetry_token; we forward to the *currently
configured* llm.base_url/llm.model — changing the model in admin settings
takes effect immediately, no range redeploy. The guest can neither pick
the destination nor the model, so this is not a general-purpose proxy —
it is a narrow chat-completions passthrough.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.domain import Session, SessionState
from ..services import settings as settings_svc

router = APIRouter(prefix="/api/llm-proxy", tags=["llm"])

_LIVE_STATES = {SessionState.READY.value, SessionState.ACTIVE.value,
                SessionState.RESETTING.value}
_MAX_MESSAGES = 40
_MAX_MSG_CHARS = 32_000
_MAX_TOKENS_CAP = 4_000


@router.post("/{token}/chat")
async def llm_chat(token: str, request: Request,
                   db: AsyncSession = Depends(get_db)):
    session = (await db.execute(
        select(Session).where(Session.telemetry_token == token))).scalar_one_or_none()
    if not session or session.state not in _LIVE_STATES:
        raise HTTPException(403, "no live session for this token")

    body = await request.json()
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise HTTPException(422, "messages required")
    def _msg(m: dict) -> dict:
        out = {"role": str(m.get("role", "user"))[:16],
               "content": str(m.get("content") or "")[:_MAX_MSG_CHARS]}
        if isinstance(m.get("tool_calls"), list):
            out["tool_calls"] = m["tool_calls"][:8]
        for key in ("tool_call_id", "name"):
            if m.get(key):
                out[key] = str(m[key])[:64]
        return out

    payload: dict = {
        "model": await settings_svc.get_setting(db, "llm.model", ""),
        "messages": [_msg(m) for m in raw_messages[-_MAX_MESSAGES:]
                     if isinstance(m, dict)],
        "stream": False,
    }
    base_url = (await settings_svc.get_setting(
        db, "llm.base_url", "")).rstrip("/")
    if not base_url or not payload["model"]:
        raise HTTPException(503, "no LLM endpoint configured (llm.base_url/llm.model)")
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        payload["tools"] = tools[:16]
    for key in ("temperature", "top_p", "max_tokens", "tool_choice"):
        if key in body:
            payload[key] = body[key]
    if isinstance(payload.get("max_tokens"), int):
        payload["max_tokens"] = min(payload["max_tokens"], _MAX_TOKENS_CAP)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as c:
            r = await c.post(f"{base_url}/chat/completions", json=payload)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"LLM upstream unreachable: {e!r}") from e
    if r.status_code != 200:
        raise HTTPException(502, f"LLM upstream {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError as e:
        raise HTTPException(502, "LLM upstream returned non-JSON") from e
