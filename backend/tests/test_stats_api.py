"""Stats-page endpoints — mock engine degrades gracefully, SMART parser and
activity aggregation are exercised against fabricated rows."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.api.routes_admin import (
    _parse_smart,
    engine_disks,
    engine_hoststats,
    engine_storage,
    stats_activity,
)
from app.models.domain import Attempt, LlmUsage, Session


async def test_engine_storage_mock_graceful(db):
    r = await engine_storage(db=db)
    assert r["ok"] is False and r["pools"] == []


async def test_engine_disks_mock_graceful(db):
    r = await engine_disks(db=db)
    assert r["ok"] is False and r["disks"] == []


async def test_engine_hoststats_mock_graceful(db):
    r = await engine_hoststats(db=db)
    assert r["ok"] is False and r["reason"] == "mock engine"


def test_parse_smart_nvme_flat():
    smart = {"temperature": 41, "power_on_hours": 8123, "percentage_used": 7,
             "spare": 100, "health": "PASSED"}
    out = _parse_smart(smart)
    assert out["temp_c"] == 41 and out["power_on_hours"] == 8123
    assert out["wearout_pct"] == 7 and out["smart_health"] == "PASSED"


def test_parse_smart_ata_attributes():
    smart = {
        "health": "PASSED",
        "attributes": [
            {"name": "Temperature_Celsius", "raw": 38},
            {"name": "Power_On_Hours", "raw": 15420},
            {"name": "Reallocated_Sector_Ct", "raw": 0},
            {"name": "Wear_Leveling_Count", "raw": 96},
        ],
    }
    out = _parse_smart(smart)
    assert out["temp_c"] == 38 and out["power_on_hours"] == 15420
    assert out["reallocated"] == 0 and out["wearout_pct"] == 4


def test_parse_smart_empty():
    assert _parse_smart({}) == {}


async def test_stats_activity_aggregates(db):
    now = datetime.now()
    # one ready session (600s deploy), one failed session
    db.add(Session(quest_id="q1", state="ready", created_at=now - timedelta(minutes=30),
                   ready_at=now - timedelta(minutes=20)))
    db.add(Session(quest_id="q1", state="failed", created_at=now - timedelta(minutes=10)))
    # attempts: one solo, one with sheet+chat, one legacy hints_used
    db.add(Attempt(quest_id="q1", session_id=1, score=100, created_at=now))
    db.add(Attempt(quest_id="q1", session_id=2, score=70, created_at=now,
                   assistance={"sheet": 1, "chat": 2}))
    db.add(Attempt(quest_id="q1", session_id=3, score=50, created_at=now,
                   hints_used=1))
    await db.commit()

    r = await stats_activity(days=30, db=db)
    assert r["ok"]
    assert r["deploys"]["sessions"] == 2 and r["deploys"]["ready"] == 1
    assert r["deploys"]["failed"] == 1 and r["deploys"]["avg_s"] == 600
    today = now.date().isoformat()
    day = next(a for a in r["attempts"] if a["day"] == today)
    assert day["count"] == 3 and day["avg_score"] == round((100 + 70 + 50) / 3)
    assert len(r["scores"]) == 3
    aids = r["aids"]
    assert aids["sheet"] == 1 and aids["chat"] == 2
    assert aids["hints"] == 1            # legacy hints_used counted
    assert aids["solo"] == 1 and aids["total"] == 2


async def test_llm_usage_breakdown_by_model_and_kind(db):
    from app.api.routes_admin import llm_usage
    db.add(LlmUsage(session_id=1, model="qwen3", kind="chat",
                    prompt_tokens=10, completion_tokens=5, total_tokens=15,
                    latency_ms=100))
    db.add(LlmUsage(session_id=1, model="qwen3", kind="reflect",
                    prompt_tokens=20, completion_tokens=5, total_tokens=25,
                    latency_ms=300))
    db.add(LlmUsage(session_id=2, model="llava", kind="vision",
                    total_tokens=8, latency_ms=200))
    await db.commit()

    r = await llm_usage(days=7, db=db)
    models = {m["model"]: m for m in r["by_model"]}
    assert models["qwen3"]["requests"] == 2 and models["qwen3"]["tokens"] == 40
    assert models["llava"]["tokens"] == 8
    kinds = {(k["kind"], k["model"]): k for k in r["by_kind"]}
    assert kinds[("chat", "qwen3")]["avg_latency_ms"] == 100
    assert kinds[("vision", "llava")]["requests"] == 1


async def test_hoststats_cache_short_circuits(db):
    """Second call inside the TTL must not hit the network."""
    import app.services.hoststats as hs
    hs._cache.update(ts=0.0, data=None)

    calls = {"n": 0}

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls["n"] += 1

            class R:
                status_code = 200

                def json(self):
                    return {"ts": 1, "cpu": {"package_c": 45.0}}

            return R()

    # fake a non-mock engine — get_engine is imported into the route module's
    # namespace, so patch it there rather than the engine singleton
    class _Pve:
        class creds:
            base_url = "https://pve.local:8006"

    class _E:
        mode = "direct"
        pve = _Pve()

    import app.api.routes_admin as ra2
    import app.services.hoststats as hs2

    async def _fake_engine(db):
        return _E()

    old_get_engine = ra2.get_engine
    old_client = hs2.httpx.AsyncClient
    ra2.get_engine = _fake_engine
    hs2.httpx.AsyncClient = lambda *a, **k: _C()
    try:
        r1 = await engine_hoststats(db=db)
        r2 = await engine_hoststats(db=db)
    finally:
        ra2.get_engine = old_get_engine
        hs2.httpx.AsyncClient = old_client
    assert r1["ok"] and r1["cpu"]["package_c"] == 45.0
    assert r2["ok"] and calls["n"] == 1
    hs._cache.update(ts=0.0, data=None)


async def test_session_live_overlay(db):
    """Console-overlay feed: kali VM vitals + host load + agent temps in one
    response; each section fails soft."""
    import time

    import app.api.routes_sessions as rs
    import app.services.hoststats as hs

    s = Session(quest_id="q", state="active", kali_vmid=103)
    db.add(s)
    await db.commit()

    class _Pve:
        class creds:
            base_url = "https://pve.local:8006"

        async def vm_status(self, vmid):
            assert vmid == 103
            return {"status": "running", "cpu": 0.42, "mem": 2e9, "maxmem": 6e9,
                    "netin": 1000, "netout": 500, "uptime": 60}

        async def node_status(self):
            return {"cpu": 0.3, "memory": {"used": 8e9, "total": 32e9},
                    "loadavg": [1.5, 1.0, 0.5], "uptime": 3600}

    class _E:
        mode = "direct"
        pve = _Pve()

    async def _fake_engine(db):
        return _E()

    old = rs.get_engine
    rs.get_engine = _fake_engine
    hs._cache.update(ts=time.monotonic(), data={"ok": True, "cpu": {"package_c": 41.0},
                                                "gpu": {"temp_c": 33.0, "util_pct": 2.0}})
    try:
        r = await rs.session_live(s.id, db=db)
    finally:
        rs.get_engine = old
        hs._cache.update(ts=0.0, data=None)
    assert r["ok"] and r["kali"]["cpu"] == 0.42 and r["kali"]["netin"] == 1000
    assert r["host"]["mem_total"] == 32e9 and r["host"]["load1"] == 1.5
    assert r["temps"] == {"cpu_c": 41.0, "gpu_c": 33.0, "gpu_util": 2.0}


async def test_session_live_mock_engine(db):
    import app.api.routes_sessions as rs
    s = Session(quest_id="q", state="active", kali_vmid=103)
    db.add(s)
    await db.commit()
    r = await rs.session_live(s.id, db=db)
    assert r["ok"] is False and r["reason"] == "mock engine"


async def test_ephemeral_replay_sticky_and_clear():
    """Sticky events replay to late subscribers; done/inactive clears the slot."""
    from app.services.events import ephemeral_clear, ephemeral_replay, publish_session
    await publish_session(42, "coach_stream",
                          {"draft_id": "d1", "content": "half"}, sticky=True)
    await publish_session(42, "coach_activity",
                          {"active": True, "text": "exec"}, sticky=True)
    evs = ephemeral_replay(42)
    assert {e["type"] for e in evs} == {"coach_stream", "coach_activity"}
    # a done draft clears only its own slot — activity survives
    await publish_session(42, "coach_stream", {"draft_id": "d1", "done": True})
    assert {e["type"] for e in ephemeral_replay(42)} == {"coach_activity"}
    ephemeral_clear(42)
    assert ephemeral_replay(42) == []


async def test_ephemeral_slots_are_per_agent():
    """Parallel subagents get their own sticky slots — a worker's inactive
    tick clears only ITS indicator, its done draft only ITS draft."""
    from app.services.events import ephemeral_replay, publish_session
    await publish_session(50, "coach_activity",
                          {"active": True, "text": "parent", "agent": "main"},
                          sticky=True)
    await publish_session(50, "coach_activity",
                          {"active": True, "text": "worker", "agent": "w1"},
                          sticky=True)
    await publish_session(50, "coach_stream",
                          {"draft_id": "d1", "agent": "w1",
                           "content": "w draft"}, sticky=True)
    assert len(ephemeral_replay(50)) == 3
    # worker goes inactive → only its own slot clears
    await publish_session(50, "coach_activity",
                          {"active": False, "agent": "w1"})
    evs = ephemeral_replay(50)
    assert {e["data"].get("agent") for e in evs
            if e["type"] == "coach_activity"} == {"main"}
    assert any(e["type"] == "coach_stream" for e in evs)
    # worker's draft finishes → only that draft's slot clears
    await publish_session(50, "coach_stream",
                          {"draft_id": "d1", "agent": "w1", "done": True})
    evs = ephemeral_replay(50)
    assert {e["type"] for e in evs} == {"coach_activity"}


async def test_ephemeral_replay_ttl_prunes():
    import time

    from app.services import events as ev_svc
    ev_svc._ephemeral[7] = {"coach_stream": (time.monotonic() - 999, {
        "type": "coach_stream", "data": {}})}
    assert ev_svc.ephemeral_replay(7) == []
    assert 7 not in ev_svc._ephemeral
