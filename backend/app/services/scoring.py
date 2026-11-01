"""Scoring + leaderboard.

score = Σ(flag.points) + time_bonus − Σ(hint.cost) − takeover_penalty
time_bonus = bonus_max · (1 − t/(2·par_s)) — full bonus only for an instant
clear, half at par_s, zero at 2·par_s.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import (
    AssistUse,
    Attempt,
    CoachAction,
    CoachMessage,
    Flag,
    FlagSubmission,
    HintUse,
    Quest,
    Session,
)


async def finalize_attempt(db: AsyncSession, session: Session) -> Attempt:
    flags = (await db.execute(select(Flag).where(Flag.quest_id == session.quest_id))).scalars().all()
    solved = {
        r.flag_key for r in (await db.execute(
            select(FlagSubmission).where(
                FlagSubmission.session_id == session.id, FlagSubmission.correct.is_(True)))
        ).scalars().all()
    }
    flag_pts = sum(f.points for f in flags if f.key in solved)

    quest = await db.get(Quest, session.quest_id)
    cfg = quest.scoring_cfg if quest else {}
    par = int(cfg.get("par_s", 1800))
    bonus_max = int(cfg.get("time_bonus_max", 200))
    takeover_cost = int(cfg.get("takeover_cost", 150))

    started = session.started_at or session.ready_at or session.created_at
    ended = session.ended_at or datetime.now(UTC).replace(tzinfo=None)
    duration = max(0, int((ended - started).total_seconds()))
    time_bonus = max(0, int(bonus_max * (1 - duration / (2 * par)))) if duration < 2 * par else 0

    hints = (await db.execute(
        select(func.count(HintUse.id), func.coalesce(func.sum(HintUse.cost), 0))
        .where(HintUse.session_id == session.id))).one()
    hint_count, hint_cost = int(hints[0] or 0), int(hints[1] or 0)

    interventions = (await db.execute(
        select(func.count(CoachAction.id)).where(
            CoachAction.session_id == session.id,
            CoachAction.tool == "exec_in_kali",
            CoachAction.status.in_(["ok", "confirmed"])))).scalar() or 0
    takeover_penalty = takeover_cost if interventions > 0 else 0

    assistance = await _assistance(db, session.id, hint_count, int(interventions))

    score = max(0, flag_pts + time_bonus - hint_cost - takeover_penalty)
    breakdown = {"flags": flag_pts, "time_bonus": time_bonus,
                 "hint_cost": hint_cost, "takeover_penalty": takeover_penalty,
                 "par_s": par}
    existing = (await db.execute(
        select(Attempt).where(Attempt.session_id == session.id))).scalar_one_or_none()
    if existing:  # idempotent — a session finalizes exactly once
        return existing
    attempt = Attempt(
        quest_id=session.quest_id, session_id=session.id, score=score,
        flags_found=len(solved), flags_total=len(flags),
        hints_used=hint_count, coach_interventions=int(interventions),
        assistance=assistance,
        breakdown=breakdown,
        duration_s=duration,
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:  # concurrent finalizer won — return theirs
        await db.rollback()
        attempt = (await db.execute(
            select(Attempt).where(Attempt.session_id == session.id))).scalar_one()
    return attempt


async def _assistance(db: AsyncSession, session_id: int, hint_count: int,
                      interventions: int) -> dict:
    """Snapshot of every aid the trainee used — shown on the leaderboard as
    'solve style' so a clean solo run reads differently from an assisted one."""
    coach_msgs = (await db.execute(
        select(func.count(CoachMessage.id)).where(
            CoachMessage.session_id == session_id,
            CoachMessage.role == "user"))).scalar() or 0
    nudges = (await db.execute(
        select(func.count(CoachMessage.id)).where(
            CoachMessage.session_id == session_id,
            CoachMessage.role == "coach",
            CoachMessage.kind.in_(["hint", "nudge", "suggestion"])))).scalar() or 0
    ui_aids = (await db.execute(
        select(AssistUse.kind, func.count(AssistUse.id))
        .where(AssistUse.session_id == session_id).group_by(AssistUse.kind))).all()
    aids = {k: int(n) for k, n in ui_aids}
    return {
        "hints": hint_count,
        "coach_msgs": int(coach_msgs),
        "coach_nudges": int(nudges),
        "takeovers": interventions,
        "sheet": aids.get("sheet", 0),
        "chat": aids.get("chat", 0),
    }


async def quest_leaderboard(db: AsyncSession, quest_id: str) -> dict:
    best = (await db.execute(
        select(Attempt).where(Attempt.quest_id == quest_id)
        .order_by(Attempt.score.desc(), Attempt.duration_s.asc()).limit(1))).scalar_one_or_none()
    # score-ordered, not chronological — the UI renders this as a ranking
    # table with a trophy on row 1, so order IS the rank
    history = (await db.execute(
        select(Attempt).where(Attempt.quest_id == quest_id)
        .order_by(Attempt.score.desc(), Attempt.duration_s.asc(),
                 Attempt.created_at.desc()).limit(50))).scalars().all()
    return {
        "best": _att(best) if best else None,
        "history": [_att(a) for a in history],
    }


async def global_leaderboard(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(
        select(Attempt.quest_id, func.max(Attempt.score).label("best"),
               func.count(Attempt.id).label("tries"))
        .group_by(Attempt.quest_id))).all()
    # best attempt per quest → its solve style (single-user scale, one pass)
    atts = (await db.execute(
        select(Attempt).order_by(Attempt.score.desc(), Attempt.duration_s.asc())
    )).scalars().all()
    best_by_quest: dict[str, Attempt] = {}
    for a in atts:
        best_by_quest.setdefault(a.quest_id, a)
    return [
        {"quest_id": q, "best_score": int(b), "attempts": int(t),
         "duration_s": best_by_quest[q].duration_s if q in best_by_quest else None,
         "breakdown": (best_by_quest[q].breakdown or {}) if q in best_by_quest else {},
         "assistance": (best_by_quest[q].assistance or {}) if q in best_by_quest else {}}
        for q, b, t in rows
    ]


def _att(a: Attempt) -> dict:
    return {
        "id": a.id, "quest_id": a.quest_id, "session_id": a.session_id,
        "score": a.score, "flags_found": a.flags_found, "flags_total": a.flags_total,
        "hints_used": a.hints_used, "coach_interventions": a.coach_interventions,
        "assistance": a.assistance or {},
        "breakdown": a.breakdown or {},
        "duration_s": a.duration_s, "created_at": a.created_at.isoformat() if a.created_at else None,
    }
