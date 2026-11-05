"""AI quest builder API — chat, draft, verify lifecycle."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..schemas import BuilderChatIn, BuilderMessageOut, BuilderSessionCreateIn, BuilderSessionOut
from ..services import builder as builder_svc
from ..services import settings as settings_svc
from ..services.sessions import SessionError
from .deps import get_current_user

router = APIRouter(prefix="/api/builder", tags=["builder"],
                   dependencies=[Depends(get_current_user)])


async def _enabled(db: AsyncSession) -> None:
    if not await settings_svc.get_setting(db, "builder.enabled", True):
        raise HTTPException(404, "quest builder is disabled")


def _out(bs) -> BuilderSessionOut:
    return BuilderSessionOut(
        id=bs.id, title=bs.title, status=bs.status, quest_id=bs.quest_id,
        verify_session_id=bs.verify_session_id, iterations=bs.iterations,
        log=bs.log or [], created_at=bs.created_at)


def _mout(m) -> BuilderMessageOut:
    return BuilderMessageOut(id=m.id, role=m.role, kind=m.kind,
                             content=m.content, meta=m.meta or {}, ts=m.ts)


@router.post("/sessions", response_model=BuilderSessionOut, status_code=201)
async def create_session(body: BuilderSessionCreateIn,
                         db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    return _out(await builder_svc.create(db, body.title))


@router.get("/sessions", response_model=list[BuilderSessionOut])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    return [_out(bs) for bs in await builder_svc.list_sessions(db)]


@router.get("/sessions/{bs_id}", response_model=BuilderSessionOut)
async def get_session(bs_id: int, db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    bs = await builder_svc.get_or_404(db, bs_id)
    if not bs:
        raise HTTPException(404, "builder session not found")
    return _out(bs)


@router.get("/sessions/{bs_id}/messages",
            response_model=list[BuilderMessageOut])
async def get_messages(bs_id: int, after_id: int = 0,
                       db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    if not await builder_svc.get_or_404(db, bs_id):
        raise HTTPException(404, "builder session not found")
    return [_mout(m) for m in await builder_svc.messages(db, bs_id, after_id)]


@router.post("/sessions/{bs_id}/chat", response_model=BuilderMessageOut)
async def chat(bs_id: int, body: BuilderChatIn,
               db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    try:
        return _mout(await builder_svc.chat(db, bs_id, body.text,
                                            body.attachments))
    except SessionError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/sessions/{bs_id}/verify", response_model=BuilderMessageOut)
async def verify(bs_id: int, db: AsyncSession = Depends(get_db)):
    await _enabled(db)
    try:
        return _mout(await builder_svc.start_verify(db, bs_id))
    except SessionError as e:
        raise HTTPException(400, str(e)) from e
