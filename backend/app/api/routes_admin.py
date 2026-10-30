"""Auth, setup wizard, settings, engine status, profile, telemetry ingest, pack mgmt."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_db
from ..models.domain import CoachMessage, UserProfile
from ..schemas import (
    CheckpointIn,
    CoachExecIn,
    CoachMessageIn,
    CoachStreamIn,
    CoachSuggestIn,
    LoginIn,
    SettingsPatch,
    TelemetryBatchIn,
    TokenOut,
)
from ..services import coach_bridge
from ..services import packs as packs_svc
from ..services import settings as settings_svc
from ..services import telemetry as telemetry_svc
from ..services.engine import get_engine, rebuild
from ..services.events import bus
from .deps import check_password, get_current_user, hash_password, make_token, require_coach

router = APIRouter(prefix="/api", tags=["admin"])


# ---------- auth / setup ----------

@router.get("/setup/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    return {
        "completed": bool(await settings_svc.get_setting(db, "setup.completed", False)),
        "engine_mode": await settings_svc.get_setting(db, "engine.mode", get_config().engine_mode),
    }


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    stored = await settings_svc.get_secret(db, "security.admin_token_hash")
    if not stored:
        # first login: adopt password as the admin credential
        await settings_svc.set_setting(db, "security.admin_token_hash", hash_password(body.password))
        return TokenOut(token=make_token())
    if not check_password(body.password, stored):
        raise HTTPException(401, "wrong password")
    return TokenOut(token=make_token())


@router.post("/setup/complete")
async def setup_complete(body: SettingsPatch, db: AsyncSession = Depends(get_db),
                         _=Depends(get_current_user)):
    """Setup wizard submission: initial settings batch + admin password.

    Open while no admin password exists; once one is set a valid bearer token
    is required — otherwise this endpoint would be a takeover vector."""
    pw = body.updates.pop("admin_password", None)
    if pw:
        await settings_svc.set_setting(db, "security.admin_token_hash", hash_password(str(pw)))
    try:
        await settings_svc.patch_settings(db, body.updates)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    await settings_svc.set_setting(db, "setup.completed", True)
    await rebuild(db)
    return {"ok": True, "token": make_token()}


# ---------- settings ----------

@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db),
                       _=Depends(get_current_user)):
    return await settings_svc.all_settings(db)


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, db: AsyncSession = Depends(get_db),
                         _=Depends(get_current_user)):
    try:
        await settings_svc.patch_settings(db, body.updates)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if any(k.startswith(("engine.", "pve", "ludus")) for k in body.updates):
        await rebuild(db)
    return await settings_svc.all_settings(db)


# ---------- engine ----------

@router.get("/engine/status")
async def engine_status(db: AsyncSession = Depends(get_db),
                        _=Depends(get_current_user)):
    engine = await get_engine(db)
    health = await engine.provider.health()
    node = None
    if engine.mode != "mock":
        try:
            node = await engine.pve.node_status()
        except Exception:
            node = None
    return {
        "mode": engine.mode,
        "health": health,
        "resources": {
            "max_ram_gb": await settings_svc.get_setting(db, "resources.max_ram_gb", 48),
            "max_vcpus": await settings_svc.get_setting(db, "resources.max_vcpus", 16),
            "max_disk_gb": await settings_svc.get_setting(db, "resources.max_disk_gb", 500),
        },
        "node": node,
    }


@router.post("/packs/sync")
async def sync_packs(db: AsyncSession = Depends(get_db),
                     _=Depends(get_current_user)):
    return await packs_svc.sync_packs(db, get_config().content_dir)


# ---------- profile ----------

@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db),
                      _=Depends(get_current_user)):
    p = await db.get(UserProfile, 1)
    if not p:
        p = UserProfile(id=1)
        db.add(p)
        await db.commit()
    return {"xp_total": p.xp_total, "track_levels": p.track_levels,
            "prefs": p.prefs, "metrics": p.metrics}


@router.patch("/profile")
async def patch_profile(body: dict, db: AsyncSession = Depends(get_db),
                        _=Depends(get_current_user)):
    p = await db.get(UserProfile, 1)
    if not p:
        p = UserProfile(id=1)
        db.add(p)
    for k in ("track_levels", "prefs", "metrics"):
        if k in body:
            setattr(p, k, body[k])
    await db.commit()
    return {"ok": True}


# ---------- telemetry ingest (Kali sidecar, token-auth not user-auth) ----------

@router.post("/telemetry")
async def telemetry_ingest(body: TelemetryBatchIn, db: AsyncSession = Depends(get_db)):
    session = await telemetry_svc.session_by_token(db, body.token)
    if not session:
        raise HTTPException(401, "invalid telemetry token")
    n = await telemetry_svc.ingest(db, session, body.events)
    return {"accepted": n}


# ---------- coach-facing REST (service token) ----------

coach_router = APIRouter(prefix="/api/coach", tags=["coach-internal"],
                         dependencies=[Depends(require_coach)])


@coach_router.get("/session/{session_id}/context")
async def coach_context(session_id: int, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.session_context(db, session_id)


@coach_router.post("/message")
async def coach_message(body: CoachMessageIn, db: AsyncSession = Depends(get_db)):
    msg = await coach_bridge.post_message(
        db, body.session_id, "coach", body.kind, body.content, body.meta)
    return {"id": msg.id}


@coach_router.post("/stream")
async def coach_stream(body: CoachStreamIn):
    """Relay an in-progress draft to the session UI. Pure bus event — nothing
    is persisted; the final send_chat call creates the real message."""
    await bus.publish(f"session.{body.session_id}", {
        "type": "coach_stream", "session_id": body.session_id,
        "data": {"draft_id": body.draft_id, "content": body.content,
                 "done": body.done, "kind": body.kind}})
    return {"ok": True}


@coach_router.post("/suggest")
async def coach_suggest(body: CoachSuggestIn, db: AsyncSession = Depends(get_db)):
    a = await coach_bridge.suggest_command(db, body.session_id, body.command, body.why)
    return {"id": a.id, "status": a.status}


@coach_router.post("/exec")
async def coach_exec(body: CoachExecIn, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.exec_in_kali(db, body.session_id, body.command)


@coach_router.post("/checkpoint")
async def coach_checkpoint(body: CheckpointIn, db: AsyncSession = Depends(get_db)):
    await coach_bridge.mark_checkpoint(db, body.session_id, body.checkpoint_id)
    return {"ok": True}


@coach_router.post("/screen")
async def coach_screen(body: dict, db: AsyncSession = Depends(get_db)):
    try:
        sid = int(body["session_id"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, "session_id required") from e
    return await coach_bridge.capture_screen(db, sid)


@coach_router.get("/messages/{session_id}")
async def coach_messages(session_id: int, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == session_id)
        .order_by(CoachMessage.id.desc()).limit(50))).scalars().all()
    return [{"role": m.role, "kind": m.kind, "content": m.content} for m in reversed(rows)]


@coach_router.get("/config")
async def coach_config(db: AsyncSession = Depends(get_db)):
    """LLM + coach runtime settings for the coach service."""
    return {
        "llm": {
            "base_url": await settings_svc.get_secret(db, "llm.base_url"),
            "api_key": await settings_svc.get_secret(db, "llm.api_key"),
            "model": await settings_svc.get_setting(db, "llm.model", ""),
            "vision_model": await settings_svc.get_setting(db, "llm.vision_model", ""),
            "temperature": await settings_svc.get_setting(db, "llm.temperature", 0.4),
            "daily_token_budget": await settings_svc.get_setting(db, "llm.daily_token_budget", 0),
        },
        "coach": {
            "enabled": await settings_svc.get_setting(db, "coach.enabled", True),
            "verbosity": await settings_svc.get_setting(db, "coach.verbosity", "normal"),
            "personality": await settings_svc.get_setting(db, "coach.personality", "mentor"),
            "reflect_interval_s": await settings_svc.get_setting(db, "coach.reflect_interval_s", 60),
            "nudge_after_s": await settings_svc.get_setting(db, "coach.nudge_after_s", 480),
            "hint_after_s": await settings_svc.get_setting(db, "coach.hint_after_s", 900),
            "action_budget": await settings_svc.get_setting(db, "coach.action_budget", 50),
        },
    }


@coach_router.post("/profile")
async def coach_update_profile(body: dict, db: AsyncSession = Depends(get_db)):
    """Coach writes back experience metrics / track levels."""
    p = await db.get(UserProfile, 1)
    if not p:
        p = UserProfile(id=1)
        db.add(p)
    if "track_levels" in body:
        p.track_levels = body["track_levels"]
    if "metrics" in body:
        p.metrics = body["metrics"]
    if "xp_total" in body:
        p.xp_total = int(body["xp_total"])
    await db.commit()
    return {"ok": True}
