"""Engine factory: builds RangeProvider + PveClient from settings/env.

mode=nested|direct → real clients; mode=mock (or missing creds in dev) → mocks.
Singleton refreshed when engine settings change (call rebuild()).
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..ranges.ludus import LudusProvider
from ..ranges.mock import MockProvider, MockPveClient
from ..ranges.pve import PveClient, PveCreds
from . import settings as settings_svc

log = structlog.get_logger(__name__)


class Engine:
    def __init__(self, provider, pve, mode: str):
        self.provider = provider
        self.pve = pve
        self.mode = mode


_engine: Engine | None = None
_engine_key: tuple | None = None
_engine_lock = asyncio.Lock()


async def _build(db: AsyncSession) -> Engine:
    cfg = get_config()
    mode = await settings_svc.get_setting(db, "engine.mode", cfg.engine_mode)
    pve_url = await settings_svc.get_secret(db, "engine.pve_url") or cfg.pve_url
    pve_node = await settings_svc.get_setting(db, "engine.pve_node", cfg.pve_node)
    pve_tok_id = await settings_svc.get_secret(db, "engine.pve_token_id") or cfg.pve_token_id
    pve_tok_sec = await settings_svc.get_secret(db, "engine.pve_token_secret") or cfg.pve_token_secret
    ludus_url = await settings_svc.get_secret(db, "engine.ludus_url") or cfg.ludus_url
    ludus_key = await settings_svc.get_secret(db, "engine.ludus_api_key") or cfg.ludus_api_key

    if mode == "mock" or not (pve_url and pve_tok_id and ludus_url):
        if mode != "mock":
            await log.awarning("engine creds incomplete — falling back to MockProvider")
        return Engine(MockProvider(), MockPveClient(), "mock")

    pve = PveClient(PveCreds(
        base_url=pve_url, token_id=pve_tok_id, token_secret=pve_tok_sec,
        verify_tls=cfg.pve_verify_tls, node=pve_node,
    ))
    provider = LudusProvider(ludus_url, ludus_key, pve, verify_tls=cfg.pve_verify_tls)
    return Engine(provider, pve, mode)


async def get_engine(db: AsyncSession) -> Engine:
    # key covers every input that changes client construction
    key = (
        await settings_svc.get_setting(db, "engine.mode", "mock"),
        await settings_svc.get_secret(db, "engine.pve_url"),
        await settings_svc.get_setting(db, "engine.pve_node", ""),
        await settings_svc.get_secret(db, "engine.pve_token_id"),
        await settings_svc.get_secret(db, "engine.pve_token_secret"),
        await settings_svc.get_secret(db, "engine.ludus_url"),
        await settings_svc.get_secret(db, "engine.ludus_api_key"),
    )
    global _engine, _engine_key
    if _engine is not None and _engine_key == key:
        return _engine
    async with _engine_lock:  # two concurrent callers must not build twice
        if _engine is not None and _engine_key == key:
            return _engine
        if _engine is not None:
            import contextlib
            with contextlib.suppress(Exception):
                await _engine.provider.close()  # type: ignore[attr-defined]
        _engine = await _build(db)
        _engine_key = key
        await log.ainfo("engine built", mode=_engine.mode)
        return _engine


async def rebuild(db: AsyncSession) -> Engine:
    global _engine_key
    _engine_key = None
    return await get_engine(db)
