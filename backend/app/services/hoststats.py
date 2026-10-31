"""Cached client for the optional pentrain-hoststats agent on the engine host
(cpu temps, gpu util/temp, fans) — shared by the admin stats page and the
session live overlay so neither polls the agent more than the cache TTL."""
from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from . import settings as settings_svc

_cache: dict = {"ts": 0.0, "data": None}


async def fetch(db: AsyncSession, engine, *, ttl_s: float = 15.0) -> dict:
    url = (await settings_svc.get_setting(db, "engine.hoststats_url", "") or "").strip()
    if not url:
        host = urlparse(engine.pve.creds.base_url).hostname
        if not host:
            return {"ok": False, "reason": "no agent url"}
        url = f"http://{host}:9100"
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["ts"] < ttl_s:
        return _cache["data"]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(url.rstrip("/") + "/stats")
        if r.status_code >= 400:
            raise httpx.HTTPError(f"hoststats {r.status_code}")
        data = {"ok": True, **r.json()}
    except Exception as e:
        data = {"ok": False, "reason": f"agent unreachable: {e}", "url": url}
    _cache.update(ts=now, data=data)
    return data
