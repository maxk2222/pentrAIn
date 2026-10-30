"""Shared test fixtures — in-memory sqlite + mock engine + synced packs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

_TEST_DB = Path(__file__).parent / "_api_test.db"
_TEST_DB.unlink(missing_ok=True)
os.environ.setdefault("PENTRAIN_DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB}")
os.environ.setdefault("PENTRAIN_ENGINE_MODE", "mock")
os.environ.setdefault("PENTRAIN_APP_SECRET", "test-secret")
os.environ.setdefault("PENTRAIN_CONTENT_DIR", str(REPO / "content" / "packs"))

from app.db import create_all, init_engine, session_factory
from app.services import engine as engine_svc
from app.services import packs as packs_svc
from app.services import sessions as sessions_svc

PACKS_DIR = REPO / "content" / "packs"


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(sessions_svc, "POLL_S", 0.05)


@pytest_asyncio.fixture
async def db(tmp_path):
    """Per-test file-backed sqlite (in-memory would shard per pooled connection,
    and background deploy tasks use their own sessions)."""
    init_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all()
    async with session_factory()() as s:
        yield s


@pytest_asyncio.fixture
async def db_with_packs(db):
    res = await packs_svc.sync_packs(db, PACKS_DIR)
    assert res["quests"] >= 5, res
    return db


@pytest.fixture(autouse=True)
def reset_engine():
    engine_svc._engine = None
    engine_svc._engine_key = None
    yield
    engine_svc._engine = None
    engine_svc._engine_key = None
