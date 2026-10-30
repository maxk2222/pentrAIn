"""Session lifecycle + gameplay (flags, hints) + leaderboards."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.domain import AssistUse, Flag, FlagSubmission, Session, TelemetryEvent
from ..schemas import (
    AssistIn,
    ConfirmActionIn,
    FlagCheckIn,
    FlagOut,
    FlagSubmitIn,
    FlagSubmitOut,
    HintUseIn,
    LeaderboardOut,
    ResetIn,
    SessionFlagsOut,
    SessionOut,
    SessionStartIn,
)
from ..services import console as console_svc
from ..services import scoring as scoring_svc
from ..services import sessions as sessions_svc
from .deps import get_current_user

router = APIRouter(prefix="/api", tags=["sessions"], dependencies=[Depends(get_current_user)])


def _out(s: Session) -> SessionOut:
    return SessionOut(
        id=s.id, quest_id=s.quest_id, state=s.state, kali_vmid=s.kali_vmid,
        autonomy_level=s.autonomy_level, coach_enabled=s.coach_enabled,
        created_at=s.created_at.isoformat() if s.created_at else None,
        ready_at=s.ready_at.isoformat() if s.ready_at else None,
        error=s.error)


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def start_session(body: SessionStartIn, db: AsyncSession = Depends(get_db)):
    try:
        s = await sessions_svc.create_session(db, body.quest_id)
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e
    if body.autonomy_level:
        s.autonomy_level = body.autonomy_level
        await db.commit()
    return _out(s)


@router.get("/sessions/active", response_model=SessionOut | None)
async def get_active(db: AsyncSession = Depends(get_db)):
    s = await sessions_svc.active_session(db)
    return _out(s) if s else None


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404)
    return _out(s)


@router.get("/sessions/{session_id}/log")
async def get_log(session_id: int, db: AsyncSession = Depends(get_db)):
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404)
    return {"log": s.deploy_log or ""}


@router.get("/sessions/{session_id}/flags", response_model=SessionFlagsOut)
async def session_flags(session_id: int, db: AsyncSession = Depends(get_db)):
    """Per-session flag progress for the objectives panel."""
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404)
    flags = (await db.execute(
        select(Flag).where(Flag.quest_id == s.quest_id))).scalars().all()
    solved = {r.flag_key for r in (await db.execute(
        select(FlagSubmission).where(
            FlagSubmission.session_id == session_id,
            FlagSubmission.correct.is_(True)))).scalars().all()}
    return SessionFlagsOut(
        flags=[FlagOut(key=f.key, name=f.name, kind=f.kind, points=f.points,
                       solved=f.key in solved) for f in flags],
        solved=len(solved), total=len(flags))


@router.get("/sessions/{session_id}/telemetry")
async def session_telemetry(session_id: int, limit: int = 100,
                            db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(TelemetryEvent).where(TelemetryEvent.session_id == session_id)
        .order_by(TelemetryEvent.id.desc()).limit(min(limit, 500)))).scalars().all()
    return [{"id": t.id, "kind": t.kind, "payload": t.payload,
             "ts": t.ts.isoformat() if t.ts else None} for t in reversed(rows)]


@router.get("/sessions/{session_id}/console")
async def console_ticket(session_id: int, db: AsyncSession = Depends(get_db)):
    """Mint a PVE VNC ticket for this session's Kali; the WS proxy consumes the
    matching port/ticket pair. The ticket doubles as the browser's RFB password."""
    result = await console_svc.issue_console_ticket(db, session_id)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.post("/sessions/{session_id}/activate", response_model=SessionOut)
async def activate(session_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return _out(await sessions_svc.activate(db, session_id))
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/flags", response_model=FlagSubmitOut)
async def submit_flag(session_id: int, body: FlagSubmitIn,
                      db: AsyncSession = Depends(get_db)):
    try:
        return await sessions_svc.submit_flag(db, session_id, body.value)
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/flags/check", response_model=FlagSubmitOut)
async def check_flag(session_id: int, body: FlagCheckIn, db: AsyncSession = Depends(get_db)):
    """Command/state flag verification — runs the check on the target VM."""
    try:
        return await sessions_svc.check_flag(db, session_id, body.flag_key)
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/hints")
async def use_hint(session_id: int, body: HintUseIn, db: AsyncSession = Depends(get_db)):
    try:
        return await sessions_svc.use_hint(db, session_id, body.hint_id)
    except sessions_svc.SessionError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/sessions/{session_id}/assist", status_code=204)
async def record_assist(session_id: int, body: AssistIn,
                        db: AsyncSession = Depends(get_db)):
    """Frontend reports an assistance panel opt-in (lazy-modal confirmed open)."""
    if not await db.get(Session, session_id):
        raise HTTPException(404, "session not found")
    db.add(AssistUse(session_id=session_id, kind=body.kind))
    await db.commit()


@router.post("/sessions/{session_id}/reset", response_model=SessionOut)
async def reset(session_id: int, body: ResetIn, db: AsyncSession = Depends(get_db)):
    try:
        return _out(await sessions_svc.reset(db, session_id, hard=body.hard))
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/abort", response_model=SessionOut)
async def abort(session_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return _out(await sessions_svc.abort(db, session_id))
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/actions/{action_id}/confirm")
async def confirm_action(session_id: int, action_id: int, body: ConfirmActionIn,
                         db: AsyncSession = Depends(get_db)):
    try:
        a = await sessions_svc.suggest_command_confirm(db, session_id, action_id, body.accept)
        return {"id": a.id, "status": a.status, "result": a.result}
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/quests/{quest_id}/leaderboard", response_model=LeaderboardOut)
async def leaderboard(quest_id: str, db: AsyncSession = Depends(get_db)):
    return await scoring_svc.quest_leaderboard(db, quest_id)


@router.get("/leaderboard")
async def global_leaderboard(db: AsyncSession = Depends(get_db)):
    return await scoring_svc.global_leaderboard(db)
