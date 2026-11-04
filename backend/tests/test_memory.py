"""Success-case memory — attack_paths: sanitize/dedupe on write,
scoped retrieval with consult-counting, confidence drift on feedback."""
from __future__ import annotations

from app.models.domain import AttackPath, Quest, Session, Track
from app.services import coach_bridge


async def _mk_session(db) -> Session:
    db.add(Track(slug="mem-net", title="mem-net", icon="i"))
    db.add(Quest(id="mem-q", track_slug="mem-net", title="q",
                 pack_path="/x"))
    s = Session(quest_id="mem-q", flag_seed="x", telemetry_token="t",
                state="active")
    db.add(s)
    await db.commit()
    return s


async def test_record_sanitizes_and_generalizes(db):
    s = await _mk_session(db)
    row = await coach_bridge.record_attack_path(
        db, s.id,
        "wpadmin → theme shell → suid root",
        ["wordpress", "suid"],
        ["recon: wpscan on 10.0.0.5 finds admin",
         "flag is pentrAIn{super_secret_flag_value}"],
        "root on 10.0.0.5")
    assert row is not None
    assert "<ip>" in row.steps[0] and "10.0.0.5" not in row.steps[0]
    assert "<ip>" in row.outcome and "10.0.0.5" not in row.outcome
    # secrets never survive into the memory row
    joined = " ".join(row.steps)
    assert "pentrAIn{" not in joined or "super_secret" not in joined


async def test_record_rejects_empty(db):
    assert await coach_bridge.record_attack_path(
        db, None, "ok title here", ["t"], []) is None


async def test_record_dedupes_similar_titles(db):
    s = await _mk_session(db)
    r1 = await coach_bridge.record_attack_path(
        db, s.id, "smb guest share → creds → ssh root",
        ["smb"], ["a", "b"], "")
    r2 = await coach_bridge.record_attack_path(
        db, s.id, "smb guest share → creds → ssh root",
        ["smb"], ["a", "b", "c"], "")
    assert r1.id == r2.id            # merged, not duplicated
    assert r2.hits == 1
    assert len(r2.steps) == 3        # richer steps kept


async def test_search_scoped_and_consult_counts(db):
    s = await _mk_session(db)
    await coach_bridge.record_attack_path(
        db, s.id, "wordpress admin → theme shell",
        ["wordpress"], ["enum", "shell"], "root")
    await coach_bridge.record_attack_path(
        db, s.id, "smb anonymous → domain creds",
        ["smb"], ["enum", "creds"], "admin")
    hits = await coach_bridge.search_attack_paths(
        db, "wordpress shell", session_id=s.id)
    assert len(hits) == 1 and hits[0]["title"].startswith("wordpress")
    # consult count bumped on the returned row
    row = await db.get(AttackPath, hits[0]["id"])
    assert row.hits >= 1
    # unrelated query finds nothing
    assert not await coach_bridge.search_attack_paths(
        db, "kubernetes etcd", session_id=s.id)


async def test_feedback_drifts_confidence_and_retires(db):
    s = await _mk_session(db)
    row = await coach_bridge.record_attack_path(
        db, s.id, "short lived path xyz", ["x"], ["s1"], "")
    c0 = row.confidence
    await coach_bridge.attack_path_feedback(db, row.id, True)
    await db.refresh(row)
    assert row.confidence > c0
    # three misses past the hit/miss balance → disabled
    for _ in range(4):
        await coach_bridge.attack_path_feedback(db, row.id, False)
    await db.refresh(row)
    assert row.status == "disabled"
    hits = await coach_bridge.search_attack_paths(
        db, "short lived", session_id=s.id)
    assert hits == []               # disabled rows never surface
