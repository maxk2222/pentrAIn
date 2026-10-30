"""Tracks, quests (library), quest detail."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.domain import Attempt, Flag, Quest, Session, SessionState, Track
from ..schemas import FlagOut, QuestDetailOut, QuestOut, TrackOut
from ..services import sessions as sessions_svc
from .deps import get_current_user

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(get_current_user)])


def _quest_out(q: Quest, *, locked=False, reason="", solved=False, best=None) -> QuestOut:
    return QuestOut(
        id=q.id, track_slug=q.track_slug, tier=q.tier, title=q.title,
        summary=q.summary, requirements=q.requirements or {},
        scoring=q.scoring_cfg or {}, locked=locked, lock_reason=reason,
        solved=solved, best_score=best, exam=q.exam)


@router.get("/tracks", response_model=list[TrackOut])
async def list_tracks(db: AsyncSession = Depends(get_db)):
    tracks = (await db.execute(select(Track).order_by(Track.order))).scalars().all()
    out: list[TrackOut] = []
    for t in tracks:
        quests = (await db.execute(
            select(Quest).where(Quest.track_slug == t.slug, Quest.active.is_(True)))).scalars().all()
        solved = (await db.execute(
            select(func.count(func.distinct(Session.quest_id)))
            .where(Session.state == SessionState.SOLVED.value)
            .where(Session.quest_id.in_([q.id for q in quests] or ["__none__"])))).scalar() or 0
        out.append(TrackOut(slug=t.slug, title=t.title, description=t.description,
                            icon=t.icon, order=t.order, quest_count=len(quests),
                            solved_count=int(solved),
                            level=1 + min(4, int(solved))))
    return out


@router.get("/quests", response_model=list[QuestOut])
async def list_quests(track: str | None = None, db: AsyncSession = Depends(get_db)):
    q = select(Quest).where(Quest.active.is_(True))
    if track:
        q = q.where(Quest.track_slug == track)
    quests = (await db.execute(
        q.order_by(Quest.track_slug, Quest.tier, Quest.exam))).scalars().all()
    solved_ids = {r[0] for r in (await db.execute(
        select(Session.quest_id).where(Session.state == SessionState.SOLVED.value)
        .distinct())).all()}
    best = {q: s for q, s in (await db.execute(
        select(Attempt.quest_id, func.max(Attempt.score)).group_by(Attempt.quest_id))).all()}
    out: list[QuestOut] = []
    for q in quests:
        ok, reason = await sessions_svc.check_unlock(db, q)
        out.append(_quest_out(q, locked=not ok, reason=reason,
                              solved=q.id in solved_ids, best=best.get(q.id)))
    return out


@router.get("/quests/{quest_id}", response_model=QuestDetailOut)
async def quest_detail(quest_id: str, db: AsyncSession = Depends(get_db)):
    q = await db.get(Quest, quest_id)
    if not q:
        raise HTTPException(404, "quest not found")
    ok, reason = await sessions_svc.check_unlock(db, q)
    solved = (await db.execute(
        select(Session.id).where(Session.quest_id == q.id,
                                 Session.state == SessionState.SOLVED.value)
        .limit(1))).scalar_one_or_none() is not None
    flags = (await db.execute(select(Flag).where(Flag.quest_id == q.id))).scalars().all()
    track = await db.get(Track, q.track_slug)
    return QuestDetailOut(
        **_quest_out(q, locked=not ok, reason=reason, solved=solved).model_dump(),
        briefing_md=q.briefing_md, defense_md=q.defense_md, topology=q.topology or {},
        cheatsheet_md=q.cheatsheet_md or "",
        track_cheatsheet_md=(track.cheatsheet_md if track else "") or "",
        hints=[{"id": h.get("id"), "cost": h.get("cost"), "stage": h.get("stage")}
               for h in q.hints_cfg or []],
        flags=[FlagOut(key=f.key, name=f.name, kind=f.kind, points=f.points) for f in flags],
    )
