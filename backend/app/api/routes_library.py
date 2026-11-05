"""Tracks, quests (library), quest detail."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.domain import Attempt, Flag, Quest, Track
from ..schemas import FlagOut, QuestDetailOut, QuestOut, TrackOut
from ..services import sessions as sessions_svc
from .deps import get_current_user

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(get_current_user)])


def _is_free(q: Quest) -> bool:
    """Free-lab sentinel quests (topology.free) — reachable via the Free
    Lab tab, hidden from the quest library lists."""
    return bool((q.topology or {}).get("free"))


def _quest_out(q: Quest, *, locked=False, reason="", solved=False, best=None,
               flag_points: int = 0) -> QuestOut:
    return QuestOut(
        id=q.id, track_slug=q.track_slug, tier=q.tier, title=q.title,
        summary=q.summary, requirements=q.requirements or {},
        scoring=q.scoring_cfg or {}, locked=locked, lock_reason=reason,
        solved=solved, best_score=best, exam=q.exam, generated=q.generated,
        max_score=flag_points + int((q.scoring_cfg or {}).get("time_bonus_max") or 0))


@router.get("/tracks", response_model=list[TrackOut])
async def list_tracks(db: AsyncSession = Depends(get_db)):
    tracks = (await db.execute(select(Track).order_by(Track.order))).scalars().all()
    out: list[TrackOut] = []
    for t in tracks:
        all_q = (await db.execute(
            select(Quest).where(Quest.track_slug == t.slug,
                                Quest.active.is_(True)))).scalars().all()
        if all_q and all(_is_free(q) for q in all_q):
            continue            # track exists only for hidden free quests
        quests = [q for q in all_q if not _is_free(q)]
        solved_ids = await sessions_svc.solved_quest_ids(db)
        solved = sum(1 for q in quests if q.id in solved_ids)
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
    quests = [x for x in (await db.execute(
        q.order_by(Quest.track_slug, Quest.tier, Quest.exam))).scalars().all()
              if not _is_free(x)]
    solved_ids = await sessions_svc.solved_quest_ids(db)
    best = {q: s for q, s in (await db.execute(
        select(Attempt.quest_id, func.max(Attempt.score)).group_by(Attempt.quest_id))).all()}
    flag_pts = {q: int(p or 0) for q, p in (await db.execute(
        select(Flag.quest_id, func.sum(Flag.points)).group_by(Flag.quest_id))).all()}
    out: list[QuestOut] = []
    for q in quests:
        ok, reason = await sessions_svc.check_unlock(db, q)
        out.append(_quest_out(q, locked=not ok, reason=reason,
                              solved=q.id in solved_ids, best=best.get(q.id),
                              flag_points=flag_pts.get(q.id, 0)))
    return out


@router.get("/quests/{quest_id}", response_model=QuestDetailOut)
async def quest_detail(quest_id: str, db: AsyncSession = Depends(get_db)):
    q = await db.get(Quest, quest_id)
    if not q:
        raise HTTPException(404, "quest not found")
    ok, reason = await sessions_svc.check_unlock(db, q)
    solved = q.id in await sessions_svc.solved_quest_ids(db)
    flags = (await db.execute(select(Flag).where(Flag.quest_id == q.id))).scalars().all()
    track = await db.get(Track, q.track_slug)
    return QuestDetailOut(
        **_quest_out(q, locked=not ok, reason=reason, solved=solved,
                     flag_points=sum(f.points for f in flags)).model_dump(),
        briefing_md=q.briefing_md, defense_md=q.defense_md, topology=q.topology or {},
        cheatsheet_md=q.cheatsheet_md or "",
        track_cheatsheet_md=(track.cheatsheet_md if track else "") or "",
        hints=[{"id": h.get("id"), "cost": h.get("cost"), "stage": h.get("stage")}
               for h in q.hints_cfg or []],
        flags=[FlagOut(key=f.key, name=f.name, kind=f.kind, points=f.points) for f in flags],
    )
