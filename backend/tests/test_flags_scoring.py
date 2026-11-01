"""Flag derivation + scoring math."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.domain import (
    AssistUse,
    CoachMessage,
    ExpectedFlag,
    Flag,
    FlagSubmission,
    Session,
)
from app.services import flags as flags_svc
from app.services import scoring as scoring_svc


def test_derive_secret_deterministic_per_seed():
    a = flags_svc.derive_flag_secret("seed1", "flag1")
    b = flags_svc.derive_flag_secret("seed1", "flag1")
    c = flags_svc.derive_flag_secret("seed2", "flag1")
    d = flags_svc.derive_flag_secret("seed1", "flag2")
    assert a == b != c != d
    assert a.startswith("pentrAIn{") and a.endswith("}")


async def test_finalize_attempt_math(db_with_packs):
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="active",
                started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=600))
    db.add(s)
    await db.commit()

    flags = (await db.execute(
        select(Flag).where(Flag.quest_id == s.quest_id))).scalars().all()
    for f in flags:
        db.add(FlagSubmission(session_id=s.id, flag_key=f.key, value="x", correct=True))
    db.add(scoring_svc.HintUse(session_id=s.id, hint_id="h1", cost=25))
    await db.commit()
    s.ended_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()

    att = await scoring_svc.finalize_attempt(db, s)
    # flag pts (300) + time bonus (par 900s, max 150, duration 600 → 150*(1-600/1800)=100)
    # - hint cost 25 = 375
    assert att.score == 375, att.score
    assert att.flags_found == 2 and att.flags_total == 2
    assert att.hints_used == 1
    assert att.breakdown == {"flags": 300, "time_bonus": 100, "hint_cost": 25,
                           "takeover_penalty": 0, "par_s": 900}


async def test_takeover_penalty_applied(db_with_packs):
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="active",
                started_at=datetime.now(UTC).replace(tzinfo=None))
    db.add(s)
    await db.flush()
    db.add(scoring_svc.CoachAction(session_id=s.id, tool="exec_in_kali",
                                   args={}, result={}, status="ok"))
    await db.commit()
    att = await scoring_svc.finalize_attempt(db, s)
    assert att.score == 50   # 150 time bonus − 100 takeover_cost (linux-t1 cfg)
    assert att.coach_interventions == 1
    assert att.breakdown["time_bonus"] == 150
    assert att.breakdown["takeover_penalty"] == 100


async def test_assistance_snapshot(db_with_packs):
    """Attempt carries a solve-style summary: hints, coach use, takeovers, UI aids."""
    db = db_with_packs
    s = Session(quest_id="linux-t1-first-foothold", state="active",
                started_at=datetime.now(UTC).replace(tzinfo=None))
    db.add(s)
    await db.flush()
    db.add_all([
        AssistUse(session_id=s.id, kind="sheet"),
        CoachMessage(session_id=s.id, role="user", kind="chat", content="stuck"),
        CoachMessage(session_id=s.id, role="coach", kind="nudge", content="look at ports"),
        CoachMessage(session_id=s.id, role="coach", kind="chat", content="hi"),
        scoring_svc.HintUse(session_id=s.id, hint_id="h1", cost=25),
    ])
    await db.commit()

    att = await scoring_svc.finalize_attempt(db, s)
    assert att.assistance == {
        "hints": 1, "coach_msgs": 1, "coach_nudges": 1,
        "takeovers": 0, "sheet": 1, "chat": 0,
    }


async def test_leaderboard_ranks_by_score(db_with_packs):
    """history is a ranking (score desc, duration asc), not a chronological
    list — the UI puts the trophy on row 1. The global row exposes the
    best run's duration + score breakdown."""
    db = db_with_packs
    for score, dur in [(300, 900), (500, 1200)]:
        s = Session(quest_id="linux-t1-first-foothold", state="solved")
        db.add(s)
        await db.flush()
        db.add(scoring_svc.Attempt(
            quest_id=s.quest_id, session_id=s.id, score=score,
            duration_s=dur,
            breakdown={"flags": score, "time_bonus": 0, "hint_cost": 0,
                       "takeover_penalty": 0, "par_s": 900}))
    await db.commit()

    board = await scoring_svc.quest_leaderboard(db, "linux-t1-first-foothold")
    assert [a["score"] for a in board["history"]] == [500, 300]
    assert board["best"]["score"] == 500

    glob = await scoring_svc.global_leaderboard(db)
    row = next(r for r in glob
               if r["quest_id"] == "linux-t1-first-foothold")
    assert row["best_score"] == 500
    assert row["duration_s"] == 1200
    assert row["breakdown"]["flags"] == 500


async def test_expected_flags_unique_per_session(db_with_packs):
    db = db_with_packs
    flags = (await db.execute(
        select(Flag).where(Flag.quest_id == "linux-t1-first-foothold"))).scalars().all()
    s1 = Session(quest_id="linux-t1-first-foothold", state="active", flag_seed="aaaa")
    s2 = Session(quest_id="linux-t1-first-foothold", state="active", flag_seed="bbbb")
    db.add_all([s1, s2])
    await db.commit()
    await flags_svc.create_expected_flags(db, s1, flags)
    await flags_svc.create_expected_flags(db, s2, flags)
    rows = (await db.execute(select(ExpectedFlag))).scalars().all()
    by_session = {}
    for r in rows:
        by_session.setdefault(r.session_id, {})[r.flag_key] = r.secret
    assert by_session[s1.id]["user-flag"] != by_session[s2.id]["user-flag"]
