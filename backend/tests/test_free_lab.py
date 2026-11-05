"""Free Lab — sentinel pack validates, free_mode reaches session_context,
and the quest stays out of normal library listings."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import session_factory
from app.main import app
from app.models.domain import Quest, Session, Track
from app.services import coach_bridge, packs

REPO = Path(__file__).resolve().parent.parent.parent

PACKS_DIR = REPO / "content" / "packs"


def test_free_pack_validates():
    spec, errs = packs.validate_quest_dir(PACKS_DIR / "lab" / "free-lab")
    assert not errs, errs
    assert spec.meta.id == "free-lab"
    assert spec.topology.free is True
    assert spec.topology.engagement is False
    assert spec.topology.vms == []            # Kali only, no targets
    assert spec.topology.kali.wan is True     # internet uplink at deploy
    assert spec.flags == []


async def _mk_session(db, quest_id, **kw):
    s = Session(quest_id=quest_id, flag_seed="x", telemetry_token="t",
                state="active", **kw)
    db.add(s)
    await db.commit()
    return s


async def test_free_lab_syncs_and_ctx_marks_free_mode(db_with_packs):
    db = db_with_packs
    q = await db.get(Quest, "free-lab")
    assert q is not None and q.topology.get("free") is True
    s = await _mk_session(db, "free-lab", kali_internet=True)
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["session"]["free_mode"] is True
    # no synthetic locked scope — free lab has no ROE to enforce
    scope = ctx.get("scope") or {}
    assert scope.get("required") is not True
    assert scope.get("locked") is not True


async def test_normal_quest_not_marked_free(db):
    db.add(Track(slug="t-free-test", title="t", icon="i"))
    db.add(Quest(id="q-normal", track_slug="t-free-test", title="q",
                 pack_path="/x", topology={"vms": [], "kali": {}}))
    await db.commit()
    s = await _mk_session(db, "q-normal")
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["session"]["free_mode"] is False


def test_library_hides_free_quest():
    with TestClient(app) as client:      # lifespan → engine + tables ready
        async def _sync():
            async with session_factory()() as db:
                await packs.sync_packs(db, PACKS_DIR)
        asyncio.run(_sync())
        quests = client.get("/api/quests").json()
        assert all(q["id"] != "free-lab" for q in quests)
        # the lab track contains ONLY the free quest → hidden from tracks too
        tracks = client.get("/api/tracks").json()
        assert all(t["slug"] != "lab" for t in tracks)
        # but the quest is still fetchable by id — the start flow needs it
        r = client.get("/api/quests/free-lab")
        assert r.status_code == 200
        assert r.json()["topology"]["free"] is True
