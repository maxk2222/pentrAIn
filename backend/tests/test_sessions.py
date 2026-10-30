"""Session lifecycle + unlock gating + flag flow (mock engine)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models.domain import Flag, Quest, Session, SessionState
from app.services import flags as flags_svc
from app.services import scoring as scoring_svc
from app.services import sessions as sessions_svc
from app.services import settings as settings_svc


async def _wait_state(session_id: int, want: str, timeout_s: float = 15.0) -> Session:
    """Poll for a state — db.get alone would return the stale identity-map copy."""
    async with sessions_svc.session_factory()() as db:
        last = None
        for _ in range(int(timeout_s / 0.1)):
            s = await db.get(Session, session_id)
            if s:
                await db.refresh(s)
                last = s
                if s.state == want:
                    return s
                if s.state == SessionState.FAILED.value:
                    raise AssertionError(f"deploy failed: {s.error}\n{s.deploy_log}")
            await asyncio.sleep(0.1)
        raise AssertionError(f"timeout waiting for {want} (last={last and last.state})")


async def test_unlock_gates_on_resource_budget(db_with_packs):
    db = db_with_packs
    # clear the tier gate so only the resource gate can fire
    for q in ("linux-t1-first-foothold", "linux-t2-privesc-chain"):
        db.add(Session(quest_id=q, state="solved"))
    await db.commit()

    quest = await db.get(Quest, "linux-t3-pivot")
    ok, _ = await sessions_svc.check_unlock(db, quest)
    assert ok  # needs 16G, budget 48G

    await settings_svc.set_setting(db, "resources.max_ram_gb", 8)
    ok, reason = await sessions_svc.check_unlock(db, quest)
    assert not ok and "RAM" in reason


async def test_unlock_gates_on_tier_progression(db_with_packs):
    db = db_with_packs
    t2 = await db.get(Quest, "linux-t2-privesc-chain")
    ok, reason = await sessions_svc.check_unlock(db, t2)
    assert not ok and "tier" in reason.lower()

    # solve t1 → t2 unlocks
    db.add(Session(quest_id="linux-t1-first-foothold", state="solved"))
    await db.commit()
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert ok


async def test_one_active_session_only(db_with_packs):
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    with pytest.raises(sessions_svc.SessionError, match="active"):
        await sessions_svc.create_session(db, "linux-t1-first-foothold")
    await sessions_svc.abort(db, s.id)
    # aborted → next session allowed
    s2 = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    await _wait_state(s2.id, "ready")
    await sessions_svc.abort(db, s2.id)


# every quest in the expanded library must survive a mock deploy —
# compile_topology + provider roundtrip + flag seeding
@pytest.mark.parametrize("quest_id", [
    "web-t3-api-chain",
    "net-t1-services", "net-t2-two-segments", "net-t3-the-dmz",
    "for-t1-break-in", "for-t2-webshell", "for-t3-correlated",
    "ad-t1-first-domain", "ad-t2-corp-lan", "ad-t3-kill-chain",
])
async def test_new_quest_deploys_on_mock(db_with_packs, quest_id):
    db = db_with_packs
    # quests with tier>1 are progression-gated — mark predecessors solved
    quest = await db.get(Quest, quest_id)
    for t in range(1, quest.tier):
        prev = (await db.execute(select(Quest.id).where(
            Quest.track_slug == quest.track_slug, Quest.tier == t))).scalar_one()
        db.add(Session(quest_id=prev, state="solved"))
    await db.commit()
    s = await sessions_svc.create_session(db, quest_id)
    await _wait_state(s.id, "ready")
    await sessions_svc.abort(db, s.id)


async def test_full_session_lifecycle_mock(db_with_packs):
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    assert s.state == "queued"

    s = await _wait_state(s.id, "ready")
    assert s.kali_vmid is not None
    assert s.target_vmids.get("target01")

    # expected flags created per-session
    quest_flags = (await db.execute(
        select(Flag).where(Flag.quest_id == s.quest_id))).scalars().all()
    expected = {
        r.flag_key: r.secret for r in (await db.execute(
            select(flags_svc.ExpectedFlag).where(
                flags_svc.ExpectedFlag.session_id == s.id))).scalars().all()
    }
    assert set(expected) == {f.key for f in quest_flags}

    await sessions_svc.activate(db, s.id)
    s = await db.get(Session, s.id)
    assert s.state == "active"

    # wrong flag
    r = await sessions_svc.submit_flag(db, s.id, "PenTrAIn{wrong}")
    assert not r["correct"] and not r["all_solved"]

    # right flags → solved + attempt scored
    for key in ("user-flag", "root-flag"):
        r = await sessions_svc.submit_flag(db, s.id, expected[key])
    assert r["correct"] and r["all_solved"]

    s = await db.get(Session, s.id)
    assert s.state == "solved"
    attempt = (await db.execute(
        select(scoring_svc.Attempt).where(scoring_svc.Attempt.session_id == s.id))
    ).scalar_one()
    assert attempt.score >= 300   # flag points + maybe time bonus
    assert attempt.flags_found == 2

    # abort destroys
    s = await sessions_svc.abort(db, s.id)
    assert s.state == "aborted"


async def test_soft_reset_regenerates_secrets(db_with_packs):
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    await sessions_svc.activate(db, s.id)
    old_seed = s.flag_seed

    await sessions_svc.reset(db, s.id, hard=False)
    s = await _wait_state(s.id, "ready")
    assert s.flag_seed != old_seed

    # expected flags regenerated with the new seed
    secrets = {r.flag_key: r.secret for r in (await db.execute(
        select(flags_svc.ExpectedFlag).where(
            flags_svc.ExpectedFlag.session_id == s.id))).scalars().all()}
    assert secrets["user-flag"] == flags_svc.derive_flag_secret(s.flag_seed, "user-flag")
    await sessions_svc.abort(db, s.id)


async def test_compile_topology_ludus_format(db_with_packs):
    quest = await db_with_packs.get(Quest, "linux-t3-pivot")
    cfg = sessions_svc.compile_topology(quest)
    vms = cfg["ludus"]
    kali = next(v for v in vms if v.get("role") == "kali")
    assert kali["template"] == "kali-x64-desktop-template"
    assert "pentrain_kali_agent" in (kali.get("roles") or [])
    names = {v["vm_name"] for v in vms}
    assert "{{ range_id }}-kali" in names
    assert "{{ range_id }}-web01" in names and "{{ range_id }}-db01" in names
