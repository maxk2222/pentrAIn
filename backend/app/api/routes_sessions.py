"""Session lifecycle + gameplay (flags, hints) + leaderboards."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.domain import AssistUse, Flag, FlagSubmission, Quest, Session, TelemetryEvent
from ..schemas import (
    AssistIn,
    AutonomyIn,
    ConfirmActionIn,
    FlagCheckIn,
    FlagOut,
    FlagSubmitIn,
    FlagSubmitOut,
    HintUseIn,
    InternetIn,
    LeaderboardOut,
    ResetIn,
    SessionFlagsOut,
    SessionOut,
    SessionStartIn,
    SubagentsIn,
)
from ..services import console as console_svc
from ..services import hoststats as hoststats_svc
from ..services import kali_net as kali_net_svc
from ..services import scoring as scoring_svc
from ..services import sessions as sessions_svc
from ..services import settings as settings_svc
from ..services.engine import get_engine
from .deps import get_current_user

router = APIRouter(prefix="/api", tags=["sessions"], dependencies=[Depends(get_current_user)])


def _out(s: Session) -> SessionOut:
    return SessionOut(
        id=s.id, quest_id=s.quest_id, state=s.state, kali_vmid=s.kali_vmid,
        autonomy_level=s.autonomy_level, coach_enabled=s.coach_enabled,
        kali_internet=bool(s.kali_internet), kali_wan_ip=s.kali_wan_ip,
        subagents_enabled=bool(s.subagents_enabled),
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


@router.get("/sessions/{session_id}/metrics")
async def session_metrics(session_id: int, db: AsyncSession = Depends(get_db)):
    """Live per-VM gauges for the stats page — cpu/mem/net per range VM."""
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine", "vms": []}
    vms: list[dict] = [{"name": "kali", "role": "kali", "vmid": s.kali_vmid}] if s.kali_vmid else []
    vms += [{"name": n, "role": "target", "vmid": v}
            for n, v in (s.target_vmids or {}).items()]
    out = []
    for v in vms:
        try:
            st = await engine.pve.vm_status(v["vmid"])
            out.append({**v,
                        "status": st.get("status"),
                        "cpu": st.get("cpu") or 0.0,
                        "mem": st.get("mem") or 0,
                        "maxmem": st.get("maxmem") or 0,
                        "balloon": st.get("balloon") or 0,
                        "netin": st.get("netin") or 0,
                        "netout": st.get("netout") or 0,
                        "uptime": st.get("uptime") or 0})
        except Exception as e:
            out.append({**v, "status": "error", "error": str(e)[:120]})
    return {"ok": True, "vms": out}


@router.get("/sessions/{session_id}/metrics/history")
async def session_metrics_history(session_id: int, timeframe: str = "hour",
                                  db: AsyncSession = Depends(get_db)):
    """RRD time series per session VM — cpu/mem sparklines for the stats page."""
    if timeframe not in ("hour", "day", "week"):
        raise HTTPException(400, "invalid timeframe")
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine", "vms": []}
    vms: list[dict] = [{"name": "kali", "role": "kali", "vmid": s.kali_vmid}] if s.kali_vmid else []
    vms += [{"name": n, "role": "target", "vmid": v}
            for n, v in (s.target_vmids or {}).items()]
    out = []
    for v in vms:
        try:
            rows = await engine.pve.vm_rrddata(v["vmid"], timeframe)
            out.append({**v, "rows": rows})
        except Exception as e:
            out.append({**v, "error": str(e)[:120]})
    return {"ok": True, "timeframe": timeframe, "vms": out}


@router.get("/sessions/{session_id}/live")
async def session_live(session_id: int, db: AsyncSession = Depends(get_db)):
    """Realtime gauges for the console overlay strip — Kali VM vitals, engine
    host load and agent temps in one call, polled every few seconds. Each
    section fails soft so the strip degrades instead of flashing errors."""
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine"}
    out: dict = {"ok": True, "kali": None, "host": None, "temps": None}
    if s.kali_vmid:
        try:
            st = await engine.pve.vm_status(s.kali_vmid)
            out["kali"] = {"status": st.get("status"),
                           "cpu": st.get("cpu") or 0.0,
                           "mem": st.get("mem") or 0,
                           "maxmem": st.get("maxmem") or 0,
                           "netin": st.get("netin") or 0,
                           "netout": st.get("netout") or 0,
                           "diskread": st.get("diskread") or 0,
                           "diskwrite": st.get("diskwrite") or 0,
                           "uptime": st.get("uptime") or 0}
        except Exception as e:
            out["kali"] = {"status": "error", "error": str(e)[:120]}
    try:
        ns = await engine.pve.node_status()
        mem = ns.get("memory") or {}
        load = ns.get("loadavg") or []
        out["host"] = {"cpu": ns.get("cpu") or 0.0,
                       "mem_used": mem.get("used") or 0,
                       "mem_total": mem.get("total") or 0,
                       "load1": float(load[0]) if load else None,
                       "uptime": ns.get("uptime") or 0}
    except Exception:
        pass
    hs = await hoststats_svc.fetch(db, engine)
    if hs.get("ok"):
        gpu = hs.get("gpu") or {}
        out["temps"] = {"cpu_c": (hs.get("cpu") or {}).get("package_c"),
                        "gpu_c": gpu.get("temp_c"),
                        "gpu_util": gpu.get("util_pct")}
    return out


@router.get("/sessions/{session_id}/console")
async def console_ticket(session_id: int, db: AsyncSession = Depends(get_db)):
    """Mint a PVE VNC ticket for this session's Kali; the WS proxy consumes the
    matching port/ticket pair. The ticket doubles as the browser's RFB password."""
    result = await console_svc.issue_console_ticket(db, session_id)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@router.get("/sessions/{session_id}/console/clipboard")
async def console_clipboard(session_id: int, db: AsyncSession = Depends(get_db)):
    """Read the Kali X clipboard via qemu-guest-agent — PVE VNC can't relay it."""
    result = await console_svc.read_guest_clipboard(db, session_id)
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


@router.post("/sessions/{session_id}/autonomy", response_model=SessionOut)
async def set_session_autonomy(session_id: int, body: AutonomyIn,
                               db: AsyncSession = Depends(get_db)):
    """Live autonomy switch — same write the chat /autonomy command uses."""
    try:
        return _out(await sessions_svc.set_autonomy(db, session_id, body.level))
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/subagents", response_model=SessionOut)
async def set_session_subagents(session_id: int, body: SubagentsIn,
                                db: AsyncSession = Depends(get_db)):
    """Live subagent toggle — same write the chat /subagents command uses."""
    try:
        return _out(await sessions_svc.set_subagents(db, session_id,
                                                     body.enabled))
    except sessions_svc.SessionError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/sessions/{session_id}/internet")
async def toggle_internet(session_id: int, body: InternetIn,
                          db: AsyncSession = Depends(get_db)):
    """Live hot-plug/remove of the kali WAN nic (net1 → wan bridge)."""
    from ..models.domain import SessionState as _S
    s = await db.get(Session, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    if not s.kali_vmid or s.state not in (_S.READY.value, _S.ACTIVE.value):
        raise HTTPException(422, f"kali not ready (state {s.state})")
    engine = await get_engine(db)
    bridge = await settings_svc.get_setting(db, "engine.kali_wan_bridge", "vmbr0")
    try:
        if body.enabled:
            quest = await db.get(Quest, s.quest_id)
            res = await kali_net_svc.apply_kali_internet(
                engine, s.kali_vmid, bridge,
                kali_net_svc.target_names_for(quest) if quest else [])
            s.kali_internet = True
            s.kali_wan_ip = res.get("ip") or None
            await db.commit()
            return {"enabled": True, "ip": res.get("ip"), "iface": res.get("iface"),
                    "mock": bool(res.get("mock"))}
        await kali_net_svc.remove_kali_internet(engine, s.kali_vmid)
        s.kali_internet = False
        s.kali_wan_ip = None
        await db.commit()
        return {"enabled": False}
    except Exception as e:
        raise HTTPException(422, str(e)[:300]) from e


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
