"""Quest pack discovery, validation, and DB sync."""
from __future__ import annotations

from sqlalchemy import func, select

from app.models.domain import Flag, Quest, Track
from app.services.packs import discover_quests, sync_packs

from .conftest import PACKS_DIR


def test_discover_packs():
    found, errors = discover_quests(PACKS_DIR)
    assert not errors, errors
    ids = {spec.meta.id for _, spec in found}
    assert {
        "linux-t1-first-foothold", "linux-t2-privesc-chain", "linux-t3-pivot",
        "web-t1-dvwa", "web-t2-juice-shop",
    } <= ids


async def test_sync_creates_tracks_quests_flags(db):
    res = await sync_packs(db, PACKS_DIR)
    assert res["quests"] >= 5
    tracks = (await db.execute(select(func.count(Track.slug)))).scalar()
    assert tracks >= 2
    quest = await db.get(Quest, "linux-t1-first-foothold")
    assert quest is not None
    assert quest.track_slug == "linux-fundamentals"
    assert quest.tier == 1
    assert "vim" in quest.coach_context_md or "student" in quest.coach_context_md
    flags = (await db.execute(
        select(Flag).where(Flag.quest_id == "linux-t1-first-foothold"))).scalars().all()
    assert {f.key for f in flags} == {"user-flag", "root-flag"}
    assert sum(f.points for f in flags) == 300


async def test_sync_maps_exam_flag(db, tmp_path):
    """meta.exam in quest.yaml lands on Quest.exam after sync."""
    q = tmp_path / "t" / "x-exam"
    q.mkdir(parents=True)
    (q / "defense.md").write_text("x")
    (q / "quest.yaml").write_text("""
apiVersion: pentrain/v1
kind: Quest
meta: {id: x-exam, track: t, tier: 1, title: X, exam: true}
""")
    await sync_packs(db, tmp_path)
    exam = await db.get(Quest, "x-exam")
    assert exam is not None and exam.exam is True
    regular = await db.get(Quest, "linux-t1-first-foothold")
    assert regular is None or regular.exam is False


async def test_sync_loads_cheatsheets(db):
    """Quest- and track-level cheatsheet.md land on their models."""
    await sync_packs(db, PACKS_DIR)
    quest = await db.get(Quest, "net-t1-services")
    assert quest is not None
    assert "mysql -h" in quest.cheatsheet_md  # the quest reference card
    track = await db.get(Track, "network-recon")
    assert track is not None
    assert "ssh -J" in track.cheatsheet_md    # the track reference card


async def test_sync_is_idempotent_and_replaces_flags(db):
    await sync_packs(db, PACKS_DIR)
    await sync_packs(db, PACKS_DIR)
    n = (await db.execute(
        select(func.count(Flag.id)).where(Flag.quest_id == "web-t1-dvwa"))).scalar()
    assert n == 2  # replaced, not duplicated


async def test_missing_defense_file_flagged(tmp_path):
    (tmp_path / "t" / "q").mkdir(parents=True)
    (tmp_path / "t" / "q" / "quest.yaml").write_text("""
apiVersion: pentrain/v1
kind: Quest
meta: {id: x, track: t, tier: 1, title: X}
""")
    _found, errors = discover_quests(tmp_path)
    assert any("defense.md" in e for e in errors)


async def test_flag_vm_reference_validated(tmp_path):
    (tmp_path / "t" / "q").mkdir(parents=True)
    (tmp_path / "t" / "q" / "defense.md").write_text("x")
    (tmp_path / "t" / "q" / "quest.yaml").write_text("""
apiVersion: pentrain/v1
kind: Quest
meta: {id: x, track: t, tier: 1, title: X}
topology:
  vms: [{name: a, template: debian-12-x64-server-template}]
flags: [{id: f, name: f, kind: file, vm: nope, file_path: /x}]
""")
    _found, errors = discover_quests(tmp_path)
    assert any("unknown vm" in e for e in errors)
