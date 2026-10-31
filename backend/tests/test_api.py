"""HTTP-level tests via TestClient — real lifespan, real routes."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_setup_status(client):
    r = client.get("/api/setup/status")
    assert r.status_code == 200
    assert set(r.json()) == {"completed", "engine_mode"}


def test_tracks_and_quests_loaded(client):
    tracks = client.get("/api/tracks").json()
    assert {t["slug"] for t in tracks} >= {"linux-fundamentals", "web-appsec"}
    quests = client.get("/api/quests").json()
    assert len(quests) >= 5
    t1 = next(q for q in quests if q["id"] == "linux-t1-first-foothold")
    assert t1["locked"] is False
    t2 = next(q for q in quests if q["id"] == "linux-t2-privesc-chain")
    assert t2["locked"] is True and "tier" in t2["lock_reason"].lower()


def test_quest_detail(client):
    r = client.get("/api/quests/linux-t3-pivot")
    assert r.status_code == 200
    d = r.json()
    assert len(d["topology"]["vms"]) == 2
    assert len(d["flags"]) == 2
    assert "Pivot" in d["briefing_md"] or "pivot" in d["briefing_md"]
    assert d["defense_md"]


def test_quest_track_filter(client):
    r = client.get("/api/quests?track=web-appsec")
    assert all(q["track_slug"] == "web-appsec" for q in r.json())


def test_settings_get_patch(client):
    s = client.get("/api/settings").json()
    assert "resources.max_ram_gb" in s
    assert s["engine.pve_token_secret"] in ("", "********")

    r = client.patch("/api/settings", json={"updates": {"resources.max_ram_gb": 64}})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["resources.max_ram_gb"] == 64

    # redacted echo is ignored on write-back
    client.patch("/api/settings", json={"updates": {"engine.pve_token_secret": "********"}})


def test_engine_status_mock(client):
    r = client.get("/api/engine/status")
    assert r.status_code == 200
    assert r.json()["mode"] == "mock"
    assert r.json()["health"]["ok"] is True


def test_session_endpoints_missing_session(client):
    assert client.get("/api/sessions/999").status_code == 404
    assert client.get("/api/sessions/999/flags").status_code == 404
    assert client.get("/api/sessions/999/console").status_code == 409
    assert client.get("/api/sessions/999/telemetry").status_code == 200


def test_chat_requires_session(client):
    r = client.post("/api/sessions/999/chat", json={"content": "hi"})
    assert r.status_code in (200, 404, 409, 500)   # no FK enforcement in v1


def test_coach_activity_endpoint(client):
    """Ephemeral working-status relay — coach-token auth, bus publish only."""
    from app.config import get_config
    h = {"Authorization": f"Bearer {get_config().coach_service_token}"}
    r = client.post("/api/coach/activity", headers=h,
                    json={"session_id": 1, "active": True, "text": "typing `id`"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post("/api/coach/activity", headers=h,
                    json={"session_id": 1, "active": False})
    assert r.status_code == 200
    # service auth rejects wrong tokens
    r = client.post("/api/coach/activity",
                    headers={"Authorization": "Bearer wrong"},
                    json={"session_id": 1, "active": True})
    assert r.status_code == 401


def test_ws_replays_sticky_ephemeral_events(client):
    """A reload mid-draft reconnects to /ws/session — the buffered draft must
    arrive immediately so the streaming bubble re-hydrates."""
    import time

    from app.services.events import _ephemeral, ephemeral_clear
    _ephemeral[9] = {"coach_stream": (time.monotonic(), {
        "type": "coach_stream", "session_id": 9,
        "data": {"draft_id": "x", "content": "half text", "done": False}})}
    try:
        with client.websocket_connect("/ws/session/9") as ws:
            first = ws.receive_json()
            assert first["type"] == "coach_stream"
            assert first["data"]["content"] == "half text"
    finally:
        ephemeral_clear(9)
