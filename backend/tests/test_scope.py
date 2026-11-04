"""Engagement scope — normalization, session snapshot, coach ctx injection."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.db import session_factory
from app.main import app
from app.models.domain import Quest, Session, Track
from app.schemas import ScopeIn
from app.services import coach_bridge, scope as scope_svc

AUTH = "ACME contract #42, valid 2026"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Deterministic resolution — no real DNS in tests."""
    async def _fake(host):
        return {"app.example.com": ["203.0.113.5"],
                "api.example.com": ["203.0.113.6"]}.get(host, [])
    monkeypatch.setattr(scope_svc, "_resolve", _fake)


def _body(**kw):
    """Raw body for service-level tests — SimpleNamespace so normalize()'s
    own validation is exercised (ScopeIn's min_length would fire first)."""
    d = {"authorization": AUTH, "nets": [], "hosts": [], "urls": [],
         "ports": []}
    d.update(kw)
    return SimpleNamespace(**d)


async def test_normalize_requires_authorization():
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(authorization="x"))
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(authorization=""))
    # the API schema enforces the same floor (422 before the service runs)
    with pytest.raises(Exception):
        ScopeIn(authorization="short")


async def test_normalize_validates_each_field():
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(nets=["not-a-net"]))
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(nets=["127.0.0.0/8"]))
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(hosts=["-bad-.com"]))
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body(ports=[0]))
    with pytest.raises(scope_svc.ScopeError):
        await scope_svc.normalize(_body())     # empty scope


async def test_normalize_full_shape():
    out = await scope_svc.normalize(_body(
        nets=["203.0.113.0/29"], hosts=["app.example.com."],
        urls=["https://api.example.com:8443/v1"], ports=[80]))
    assert out["locked"] and out["mode"] == "external-engagement"
    assert out["authorized_by"].startswith("ACME")
    # hostname case/trailing-dot normalized; resolved IPs pinned as /32 nets
    assert "app.example.com" in out["hosts"]
    assert "api.example.com" in out["hosts"]
    assert "203.0.113.5/32" in out["nets"] and "203.0.113.6/32" in out["nets"]
    assert out["resolved"]["app.example.com"] == ["203.0.113.5"]
    # url port joined the whitelist
    assert out["ports"] == [80, 8443]


async def _mk_session(db) -> Session:
    """Minimal track+quest+session graph — session_context dereferences
    quest.topology, so a bare Session row isn't enough."""
    db.add(Track(slug="scope-net", title="scope-net", icon="i"))
    db.add(Quest(id="scope-q", track_slug="scope-net", title="q",
                 pack_path="/x"))
    s = Session(quest_id="scope-q", flag_seed="x", telemetry_token="t",
                state="active")
    db.add(s)
    await db.commit()
    return s


async def test_ctx_carries_scope(db):
    s = await _mk_session(db)
    s.scope_json = json.dumps({"locked": True, "nets": ["203.0.113.0/29"],
                               "hosts": [], "ports": []})
    await db.commit()
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["scope"]["locked"] is True
    assert ctx["scope"]["nets"] == ["203.0.113.0/29"]


async def test_ctx_scope_none_when_unset(db):
    s = await _mk_session(db)
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["scope"] is None


async def _mk_session_row() -> int:
    async with session_factory()() as db:
        s = await _mk_session(db)
        return s.id


def test_scope_endpoints():
    with TestClient(app) as client:      # lifespan → engine + tables ready
        sid = asyncio.run(_mk_session_row())
        r = client.post(f"/api/sessions/{sid}/scope", json={
            "authorization": AUTH,
            "nets": ["203.0.113.0/29"], "hosts": ["app.example.com"]})
        assert r.status_code == 200, r.text
        scope = r.json()["scope"]
        assert scope["locked"] and "203.0.113.5/32" in scope["nets"]
        # session GET echoes it
        r = client.get(f"/api/sessions/{sid}")
        assert r.json()["scope"]["locked"] is True
        # validation failure → 422 with the reason
        r = client.post(f"/api/sessions/{sid}/scope", json={
            "authorization": AUTH, "nets": ["bogus"]})
        assert r.status_code == 422 and "invalid CIDR" in r.text
        # missing authorization → 422 (pydantic min_length)
        r = client.post(f"/api/sessions/{sid}/scope", json={
            "authorization": "", "nets": ["203.0.113.0/29"]})
        assert r.status_code == 422
        # delete unlocks
        r = client.delete(f"/api/sessions/{sid}/scope")
        assert r.status_code == 200
        assert client.get(f"/api/sessions/{sid}").json()["scope"] is None
