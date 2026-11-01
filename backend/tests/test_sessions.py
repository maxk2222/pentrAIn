"""Session lifecycle + unlock gating + flag flow (mock engine)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models.domain import Attempt, Flag, Quest, Session, SessionState
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


async def _mark_solved(db, *qids: str) -> None:
    """Record quests as solved the way the game stores it — a finished Session
    plus its finalized Attempt (attempts are the progression anchor, not
    session.state, which abort() may end honestly)."""
    for qid in qids:
        s = Session(quest_id=qid, state="solved")
        db.add(s)
        await db.flush()
        db.add(Attempt(quest_id=qid, session_id=s.id, score=100))
    await db.commit()


async def _solve_prereqs(db, quest: Quest) -> None:
    """Mark everything check_unlock needs as solved for `quest`.

    Non-exam quests at tier <= quest.tier in the same track — for exam
    quests the same-tier peers are the actual gate, for regular quests
    marking lower tiers solved satisfies the any-solved predecessor rule.
    """
    rows = (await db.execute(select(Quest.id).where(
        Quest.track_slug == quest.track_slug,
        Quest.tier <= quest.tier,
        Quest.exam.is_not(True)))).scalars().all()
    await _mark_solved(db, *rows)


async def test_unlock_gates_on_resource_budget(db_with_packs):
    db = db_with_packs
    # clear the tier gate so only the resource gate can fire
    await _mark_solved(db, "linux-t1-first-foothold", "linux-t2-privesc-chain")

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
    await _mark_solved(db, "linux-t1-first-foothold")
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert ok


async def test_unlock_tier_any_solved(db_with_packs):
    """Multiple quests share a tier — ANY solved predecessor unlocks the next."""
    db = db_with_packs
    t2 = await db.get(Quest, "linux-t2-privesc-chain")
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert not ok

    # solving the *other* tier-1 quest (not the canonical first) unlocks t2
    await _mark_solved(db, "linux-t1-suid-hunt")
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert ok


async def test_exam_gate_requires_all_tier_quests(db_with_packs):
    """meta.exam quests stay locked until every same-tier non-exam quest is solved."""
    db = db_with_packs
    exam = await db.get(Quest, "linux-t1-exam")
    assert exam is not None and exam.exam

    ok, reason = await sessions_svc.check_unlock(db, exam)
    assert not ok and "exam" in reason.lower()

    # one of the two t1 quests is not enough
    await _mark_solved(db, "linux-t1-first-foothold")
    ok, _ = await sessions_svc.check_unlock(db, exam)
    assert not ok

    # all t1 non-exam quests solved → exam unlocks
    await _mark_solved(db, "linux-t1-suid-hunt")
    ok, _ = await sessions_svc.check_unlock(db, exam)
    assert ok


async def test_exam_solve_does_not_unlock_next_tier(db_with_packs):
    """Exams are capstones — solving one alone must not open tier+1."""
    db = db_with_packs
    await _mark_solved(db, "linux-t1-exam")
    t2 = await db.get(Quest, "linux-t2-privesc-chain")
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert not ok


async def test_solved_progression_survives_abort(db_with_packs):
    """Aborting a solved session tears the range down but must NOT erase
    progression — attempts anchor 'solved', not the session lifecycle."""
    db = db_with_packs
    s = Session(quest_id="linux-t1-suid-hunt", state="solved")
    db.add(s)
    await db.flush()
    db.add(Attempt(quest_id="linux-t1-suid-hunt", session_id=s.id, score=100))
    await db.commit()

    await sessions_svc.abort(db, s.id)
    t2 = await db.get(Quest, "linux-t2-privesc-chain")
    ok, _ = await sessions_svc.check_unlock(db, t2)
    assert ok


async def test_t2_exam_needs_prev_tier_and_all_peers(db_with_packs):
    """A t2 exam is gated twice: any t1 solve AND all t2 non-exam quests."""
    db = db_with_packs
    exam = await db.get(Quest, "linux-t2-exam")
    assert exam is not None and exam.exam

    # t2 peers solved but no t1 → still locked on the tier gate
    await _mark_solved(db, "linux-t2-privesc-chain", "linux-t2-wildcard-cron")
    ok, _ = await sessions_svc.check_unlock(db, exam)
    assert not ok

    # + one t1 quest → fully unlocked
    await _mark_solved(db, "linux-t1-first-foothold")
    ok, _ = await sessions_svc.check_unlock(db, exam)
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


# every quest in the library must survive a mock deploy —
# compile_topology + provider roundtrip + flag seeding.
# Discovered dynamically so newly-authored quests are covered automatically.
from app.services.packs import discover_quests  # noqa: E402

from .conftest import PACKS_DIR  # noqa: E402

_ALL_QUEST_IDS = [s.meta.id for _d, s in discover_quests(PACKS_DIR)[0]]


@pytest.mark.parametrize("quest_id", _ALL_QUEST_IDS)
async def test_new_quest_deploys_on_mock(db_with_packs, quest_id):
    db = db_with_packs
    # progression + exam gates — mark all non-exam prereqs solved
    quest = await db.get(Quest, quest_id)
    await _solve_prereqs(db, quest)
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
    r = await sessions_svc.submit_flag(db, s.id, "pentrAIn{wrong}")
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


async def test_command_flag_on_kali_uses_kali_vmid(db_with_packs):
    """flags with vm: kali run the check shell on the trainee console VM —
    scripting quests verify their artifacts there."""
    from app.services import engine as engine_svc
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    engine = await engine_svc.get_engine(db)
    flag = Flag(quest_id=s.quest_id, key="kali-check", name="k",
                kind="command", points=10,
                command_spec={"vm": "kali", "cmd": "id", "expect": "mock"})
    assert await flags_svc.check_command_flag(db, engine, s, flag)
    assert engine.pve.exec_log[-1][0] == s.kali_vmid
    await sessions_svc.abort(db, s.id)


async def test_file_flag_on_kali_injects_to_kali_vmid(db_with_packs):
    """kind=file + vm: kali lands the flag on the trainee console VM —
    same resolver as command flags, exercised through inject_flags."""
    from app.services import engine as engine_svc
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    engine = await engine_svc.get_engine(db)
    flag = Flag(quest_id=s.quest_id, key="kali-file", name="k",
                kind="file", points=10,
                command_spec={"vm": "kali", "file_path": "/root/kali-flag.txt"})
    await flags_svc.create_expected_flags(db, s, [flag])
    logs = await flags_svc.inject_flags(db, engine, s, [flag])
    assert (s.kali_vmid, "/root/kali-flag.txt") in engine.pve.files
    assert any("injected" in line for line in logs)
    await sessions_svc.abort(db, s.id)


async def test_check_flag_rejects_noncommand_flag(db_with_packs):
    """check_flag on a file-kind flag surfaces the real reason, not 'None'."""
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    await sessions_svc.activate(db, s.id)
    with pytest.raises(sessions_svc.SessionError, match="not a command flag"):
        await sessions_svc.check_flag(db, s.id, "user-flag")
    await sessions_svc.abort(db, s.id)


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
    kali = next(v for v in vms if "kali" in v["vm_name"])
    assert kali["template"] == "kali-x64-desktop-template"
    assert kali["ram_gb"] == 6 and kali["ram_min_gb"] == 3
    for v in vms:
        if v is not kali:
            assert v["ram_min_gb"] == v["ram_gb"] // 2
    assert cfg["router"] == {"template": "debian-12-x64-server-template",
                             "ram_gb": 2, "ram_min_gb": 1}
    assert "pentrain_kali_agent" in (kali.get("roles") or [])
    names = {v["vm_name"] for v in vms}
    assert "{{ range_id }}-kali" in names
    assert "{{ range_id }}-web01" in names and "{{ range_id }}-db01" in names


async def test_metrics_history_rejects_bad_timeframe(db_with_packs):
    from fastapi import HTTPException

    from app.api.routes_sessions import session_metrics_history
    s = Session(quest_id="linux-t1-first-foothold", state="ready", kali_vmid=100)
    db_with_packs.add(s)
    await db_with_packs.commit()
    with pytest.raises(HTTPException) as ei:
        await session_metrics_history(s.id, "fortnight", db_with_packs)
    assert ei.value.status_code == 400


async def test_metrics_history_mock_engine(db_with_packs):
    from app.api.routes_sessions import session_metrics_history
    s = Session(quest_id="linux-t1-first-foothold", state="ready",
                kali_vmid=100, target_vmids={"target01": 101})
    db_with_packs.add(s)
    await db_with_packs.commit()
    r = await session_metrics_history(s.id, "hour", db_with_packs)
    assert r["ok"] is False and r["reason"] == "mock engine" and r["vms"] == []


async def test_metrics_history_missing_session(db_with_packs):
    from fastapi import HTTPException

    from app.api.routes_sessions import session_metrics_history
    with pytest.raises(HTTPException) as ei:
        await session_metrics_history(999, "hour", db_with_packs)
    assert ei.value.status_code == 404


# ---------- deploy resilience: resume after backend restart ----------


async def _engine_and_range(db, state: str):
    """Fabricate a mock range in `state` and return (engine, provider)."""
    from app.ranges.base import RangeState
    from app.services import engine as engine_svc
    engine = await engine_svc.get_engine(db)
    p = engine.provider
    await p.deploy_range("x", {"ludus": [{"vm_name": "MO-kali", "role": "kali"}]})
    rng = next(iter(p._ranges.values()))
    rng.state = RangeState(state)
    return engine, p


async def test_resume_deploying_running_finalizes(db_with_packs):
    """Restart mid-deploy, range already RUNNING → resume finalizes to ready."""
    db = db_with_packs
    await _engine_and_range(db, "running")
    s = Session(quest_id="linux-t1-first-foothold", state="deploying", range_id="MO")
    db.add(s)
    await db.commit()
    await sessions_svc._resume(s.id)
    await db.refresh(s)
    assert s.state == "ready" and s.kali_vmid is not None


async def test_resume_deploying_absent_redeploys(db_with_packs):
    """Config upload died with the process → resume starts the deploy fresh."""
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="deploying", range_id="MO")
    db.add(s)
    await db.commit()
    await sessions_svc._resume(s.id)
    s = await _wait_state(s.id, "ready")
    assert s.kali_vmid is not None


async def test_resume_deploying_failed_marks_failed(db_with_packs):
    db = db_with_packs
    await _engine_and_range(db, "failed")
    s = Session(quest_id="linux-t1-first-foothold", state="deploying", range_id="MO")
    db.add(s)
    await db.commit()
    await sessions_svc._resume(s.id)
    await db.refresh(s)
    assert s.state == "failed" and "while backend was down" in (s.error or "")


async def test_resume_queued_deploys(db_with_packs):
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="queued")
    db.add(s)
    await db.commit()
    await sessions_svc._resume(s.id)
    s = await _wait_state(s.id, "ready")
    assert s.kali_vmid is not None


async def test_resume_resetting_running_hard_resets(db_with_packs):
    """Interrupted reset over a dirty range → redeploy superset → ready."""
    db = db_with_packs
    _, p = await _engine_and_range(db, "running")
    s = Session(quest_id="linux-t1-first-foothold", state="resetting", range_id="MO")
    db.add(s)
    await db.commit()
    await sessions_svc._resume(s.id)
    s = await _wait_state(s.id, "ready")
    assert s.kali_vmid is not None
    assert any("destroy" in line or "deploying" in line
               for line in next(iter(p._ranges.values())).logs)


async def test_watch_range_tolerates_transient_errors(db_with_packs, monkeypatch):
    """A flaky status() must not kill a deploy — fail only on a real streak."""
    db = db_with_packs
    engine, p = await _engine_and_range(db, "running")
    s = Session(quest_id="linux-t1-first-foothold", state="deploying", range_id="MO")
    db.add(s)
    await db.commit()

    calls = {"n": 0}
    real_status = p.status

    async def flaky(range_id=None):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("ludus 502")
        return await real_status(range_id)

    monkeypatch.setattr(p, "status", flaky)
    st = await sessions_svc._watch_range(db, engine, s)
    assert st.state.value == "running" and calls["n"] == 4

    calls["n"] = 0

    async def dead(range_id=None):
        raise RuntimeError("ludus down")

    monkeypatch.setattr(p, "status", dead)
    with pytest.raises(sessions_svc.SessionError, match="unreachable"):
        await sessions_svc._watch_range(db, engine, s)


async def test_resume_inflight_sweeps_states(db_with_packs):
    db = db_with_packs
    for state in ("queued", "deploying"):
        db.add(Session(quest_id="linux-t1-first-foothold", state=state))
    db.add(Session(quest_id="linux-t1-first-foothold", state="active"))  # not inflight
    await db.commit()
    n = await sessions_svc.resume_inflight()
    assert n == 2
    # spawned tasks finish on their own — wait for both to reach a terminal/ready state
    for _ in range(200):
        states = (await db.execute(
            select(Session.state).where(Session.state.in_(["queued", "deploying"])))).all()
        if not states:
            break
        await asyncio.sleep(0.05)
    done = (await db.execute(select(Session.state))).scalars().all()
    assert done.count("ready") == 2 and "active" in done


# ---------- live autonomy switching ----------

async def test_set_autonomy_persists_and_announces(db_with_packs):
    """set_autonomy writes the level, posts a system message and broadcasts —
    the coach picks it up from session_context on its next turn."""
    from app.models.domain import CoachMessage
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")

    s = await sessions_svc.set_autonomy(db, s.id, 4)
    assert s.autonomy_level == 4
    msg = (await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == s.id)
        .order_by(CoachMessage.id.desc()).limit(1))).scalar_one()
    assert msg.role == "system" and "Autonomous" in msg.content
    await sessions_svc.abort(db, s.id)


async def test_set_autonomy_rejects_terminal_and_bad_levels(db_with_packs):
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="solved")
    db.add(s)
    await db.commit()
    with pytest.raises(sessions_svc.SessionError, match="locked"):
        await sessions_svc.set_autonomy(db, s.id, 4)
    s.state = "ready"
    await db.commit()
    for bad in (0, 5):
        with pytest.raises(sessions_svc.SessionError, match="1-4"):
            await sessions_svc.set_autonomy(db, s.id, bad)


async def test_chat_slash_autonomy_paths(db_with_packs):
    """Slash commands never reach post_message — they'd surface as an
    OPERATOR_DIRECTIVE in L4 prompts and the model would 'execute' them."""
    from app.api.routes_streams import _chat_slash
    from app.models.domain import CoachMessage
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")

    # not a slash command → None
    assert await _chat_slash(db, s.id, "hello coach") is None
    assert await _chat_slash(db, s.id, "/restart everything") is None

    # status — no arg
    r = await _chat_slash(db, s.id, "/autonomy")
    assert r["id"] < 0                       # negative echo id, no dedupe clash

    # name + digit aliases all resolve
    r = await _chat_slash(db, s.id, "/level takeover")
    assert r["id"] < 0
    s = await db.get(Session, s.id)
    assert s.autonomy_level == 4
    r = await _chat_slash(db, s.id, "/mode 2")
    s = await db.get(Session, s.id)
    assert s.autonomy_level == 2

    # bogus level → usage reply, level unchanged
    r = await _chat_slash(db, s.id, "/autonomy bogus")
    assert r["id"] < 0
    msgs = list((await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == s.id)
        .order_by(CoachMessage.id.desc()).limit(1))).scalars())
    assert "Usage" in msgs[0].content
    # no user-role message was persisted for any slash variant
    user_msgs = (await db.execute(
        select(CoachMessage).where(
            CoachMessage.session_id == s.id, CoachMessage.role == "user"))).all()
    assert not user_msgs
    await sessions_svc.abort(db, s.id)


# ---------- home-lab lan-assessment mode ----------

async def test_wan_quest_auto_uplinks_and_stores_lease(db_with_packs):
    """topology.kali.wan attaches net1 at deploy — session.kali_internet
    ends True on the mock path, and the lease field exists (mock leaves
    it empty, which is what the lan.scope_cidr fallback covers)."""
    db = db_with_packs
    s = await sessions_svc.create_session(db, "lab-t1-assessment")
    s = await _wait_state(s.id, "ready")
    assert s.kali_internet is True
    assert hasattr(s, "kali_wan_ip")          # column exists; mock leaves None
    assert set(s.target_vmids) == {"kali"}     # kali-only range
    await sessions_svc.abort(db, s.id)


async def test_compile_topology_wan_and_kali_roles():
    """KaliSpec.wan rides in the stored topology; KaliSpec.roles merge after
    the mandatory pentrain_kali_agent."""
    from app.services.sessions import compile_topology
    q = Quest(id="x", track_slug="home-lab", tier=1, title="x",
              topology={"kali": {"wan": True, "roles": ["pentrain_home_lab",
                                                     {"name": "extra"}]},
                        "vms": []})
    cfg = compile_topology(q)
    kali = cfg["ludus"][0]
    assert kali["roles"] == ["pentrain_kali_agent", "pentrain_home_lab",
                            {"name": "extra"}]
    assert len(cfg["ludus"]) == 1             # kali only — no targets
    assert q.topology["kali"]["wan"] is True  # survives model_dump storage


async def test_session_context_reports_scope(db_with_packs):
    """home-lab sessions surface scope + lan-scope target to the coach —
    the only 'where to aim' the model gets with zero range VMs."""
    from app.services import coach_bridge
    db = db_with_packs
    s = await sessions_svc.create_session(db, "lab-t1-assessment")
    s = await _wait_state(s.id, "ready")

    # explicit setting wins
    await settings_svc.set_setting(db, "lan.scope_cidr", "192.168.7.0/24")
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["quest"]["scope"] == "192.168.7.0/24"
    assert ctx["quest"]["mode"] == "lan-assessment"
    assert ctx["quest"]["targets"] == [
        {"name": "lan-scope", "ip": "192.168.7.0/24"}]

    # lease fallback when the setting is empty — _wait_state returns a
    # detached row (own session_factory), so re-load into the test session
    await settings_svc.set_setting(db, "lan.scope_cidr", "")
    s = await db.get(Session, s.id)
    s.kali_wan_ip = "192.168.3.131"
    await db.commit()
    ctx = await coach_bridge.session_context(db, s.id)
    assert ctx["quest"]["scope"] == "192.168.3.131/24"

    # a normal quest never gets a scope
    s2 = await db.get(Session, s.id)
    await sessions_svc.abort(db, s2.id)
    s2 = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s2 = await _wait_state(s2.id, "ready")
    ctx = await coach_bridge.session_context(db, s2.id)
    assert ctx["quest"]["scope"] is None
    await sessions_svc.abort(db, s2.id)


async def test_set_subagents_and_slash_paths(db_with_packs):
    """set_subagents mirrors set_autonomy — field write, system message,
    broadcast; the /subagents slash stays out of post_message."""
    from app.api.routes_streams import _chat_slash
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    assert s.subagents_enabled is False

    s = await sessions_svc.set_subagents(db, s.id, True)
    assert s.subagents_enabled is True

    r = await _chat_slash(db, s.id, "/subagents")           # status line
    assert r["id"] < 0
    r = await _chat_slash(db, s.id, "/subagents off")
    assert r["id"] < 0
    s = await db.get(Session, s.id)
    assert s.subagents_enabled is False
    r = await _chat_slash(db, s.id, "/subs on")             # alias
    s = await db.get(Session, s.id)
    assert s.subagents_enabled is True
    r = await _chat_slash(db, s.id, "/subagents bogus")     # usage reply
    assert r["id"] < 0

    s.state = "solved"
    await db.commit()
    with pytest.raises(sessions_svc.SessionError, match="locked"):
        await sessions_svc.set_subagents(db, s.id, True)
    await sessions_svc.abort(db, s.id)


async def test_session_context_carries_reference_and_tools(db_with_packs):
    """The coach's knowledge base rides in session_context: track + quest
    cheatsheets (tool syntax/methodology) and the live kali_tools probe."""
    from app.services import coach_bridge
    db = db_with_packs
    s = await sessions_svc.create_session(db, "linux-t1-first-foothold")
    s = await _wait_state(s.id, "ready")
    s = await db.get(Session, s.id)
    s.kali_tools = "nmap\nsmbclient\nmysql"
    await db.commit()
    ctx = await coach_bridge.session_context(db, s.id)
    assert "nmap" in ctx["quest"]["track_cheatsheet"]      # linux cheatsheet
    assert ctx["quest"]["cheatsheet"]                    # quest-local card
    assert ctx["session_tools"] == "nmap\nsmbclient\nmysql"
    await sessions_svc.abort(db, s.id)
