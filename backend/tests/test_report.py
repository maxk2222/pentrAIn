"""Findings/report assembly — backend replay of record_finding rows and
the markdown report endpoint."""
from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.db import session_factory
from app.main import app
from app.models.domain import CoachAction, Quest, Session, Track
from app.services import report as report_svc


async def _mk(db) -> Session:
    db.add(Track(slug="rep-net", title="rep-net", icon="i"))
    db.add(Quest(id="rep-q", track_slug="rep-net", title="q", pack_path="/x"))
    s = Session(quest_id="rep-q", flag_seed="x", telemetry_token="t",
                state="active")
    db.add(s)
    await db.commit()
    return s


def _action(sid: int, args: dict) -> CoachAction:
    return CoachAction(session_id=sid, tool="record_finding",
                       args=args, status="ok")


async def test_findings_replay_create_dedup_update(db):
    s = await _mk(db)
    db.add_all([
        _action(s.id, {"title": "SMB guest", "host": "10.0.0.5",
                       "sev": "high", "status": "candidate"}),
        # same title+host → dedup-update (evidence enriches)
        _action(s.id, {"title": "SMB guest", "host": "10.0.0.5",
                       "evidence": "anon IPC$ listing"}),
        _action(s.id, {"title": "weak tls", "host": "10.0.0.5:443"}),
    ])
    await db.commit()
    finds = await report_svc.findings(db, s.id)
    assert len(finds) == 2
    v1 = next(v for v in finds if v["title"] == "SMB guest")
    assert v1["id"] == "v1" and v1["sev"] == "high"
    assert v1["evidence"] == "anon IPC$ listing"
    assert v1["status"] == "candidate"


async def test_findings_confirmed_needs_evidence_and_update_by_id(db):
    s = await _mk(db)
    db.add_all([
        _action(s.id, {"title": "RCE", "host": "h", "status": "confirmed"}),
        # bare confirmed without evidence → demoted to candidate
        _action(s.id, {"id": "v1", "status": "confirmed",
                       "evidence": "uid=0(root) gid=0(root)"}),
        # unknown id is a no-op
        _action(s.id, {"id": "v42", "status": "rejected"}),
    ])
    await db.commit()
    finds = await report_svc.findings(db, s.id)
    assert len(finds) == 1 and finds[0]["status"] == "confirmed"
    assert finds[0]["evidence"].startswith("uid=0")


async def test_coverage_replay(db):
    s = await _mk(db)
    db.add_all([
        CoachAction(session_id=s.id, tool="record_coverage",
                    args={"surface": "10.0.0.5:445", "outcome": "testing"},
                    status="ok"),
        CoachAction(session_id=s.id, tool="update_coverage",
                    args={"surface": "10.0.0.5:445", "outcome": "confirmed",
                          "evidence": "guest read ok"},
                    status="ok"),
        # update on a never-recorded surface is ignored
        CoachAction(session_id=s.id, tool="update_coverage",
                    args={"surface": "10.0.0.9:22", "outcome": "testing"},
                    status="ok"),
    ])
    await db.commit()
    cov = await report_svc.coverage(db, s.id)
    assert list(cov) == ["10.0.0.5:445"]
    assert cov["10.0.0.5:445"]["outcome"] == "confirmed"


async def test_report_md_groups_and_scope(db):
    s = await _mk(db)
    s.scope_json = json.dumps({"locked": True, "nets": ["203.0.113.0/29"],
                               "hosts": ["app.example.com"],
                               "ports": [443], "authorized_by": "op",
                               "authorized_at": "2026-11-04"})
    db.add_all([
        _action(s.id, {"title": "RCE", "host": "203.0.113.3",
                       "status": "confirmed", "sev": "critical",
                       "evidence": "uid=0(root) shell via template injection",
                       "next": "patch template engine"}),
        _action(s.id, {"title": "weak tls", "host": "app.example.com:443"}),
    ])
    await db.commit()
    finds = await report_svc.findings(db, s.id)
    md = report_svc.report_md(s, finds, {})
    assert "**Authorized scope** (op" in md
    assert "### [v1] RCE — CRITICAL on 203.0.113.3" in md
    assert "Candidates (unvalidated)" in md and "weak tls" in md


def test_findings_and_report_endpoints():
    with TestClient(app) as client:
        sid = asyncio.run(_mk_via_factory())
        r = client.get(f"/api/sessions/{sid}/findings")
        assert r.status_code == 200 and r.json() == {"findings": []}
        asyncio.run(_write_actions(sid))
        r = client.get(f"/api/sessions/{sid}/findings")
        finds = r.json()["findings"]
        assert len(finds) == 1 and finds[0]["title"] == "open share"
        r = client.get(f"/api/sessions/{sid}/report")
        assert r.status_code == 200
        assert "## Findings" in r.json()["markdown"]


async def _mk_via_factory() -> int:
    async with session_factory()() as db:
        s = await _mk(db)
        return s.id


async def _write_actions(sid: int):
    async with session_factory()() as db:
        db.add(_action(sid, {"title": "open share", "host": "10.0.0.5",
                             "status": "confirmed", "sev": "medium",
                             "evidence": "anonymous read of public/"}))
        await db.commit()
