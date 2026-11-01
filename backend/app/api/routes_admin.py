"""Auth, setup wizard, settings, engine status, profile, telemetry ingest, pack mgmt."""
import contextlib
import re
import time
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_config
from ..db import get_db
from ..models.domain import Attempt, CoachMessage, LlmUsage, Session, SessionState, UserProfile
from ..schemas import (
    CheckpointIn,
    CoachActivityIn,
    CoachExecIn,
    CoachFlagCheckIn,
    CoachFlagIn,
    CoachMessageIn,
    CoachStreamIn,
    CoachSuggestIn,
    CoachTypeIn,
    LoginIn,
    SettingsPatch,
    TelemetryBatchIn,
    TokenOut,
)
from ..services import coach_bridge
from ..services import console as console_svc
from ..services import hoststats as hoststats_svc
from ..services import packs as packs_svc
from ..services import settings as settings_svc
from ..services import telemetry as telemetry_svc
from ..services.engine import get_engine, rebuild
from ..services.events import publish_session
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
    vms = None
    if engine.mode != "mock":
        try:
            node = await engine.pve.node_status()
        except Exception:
            node = None
        try:
            res = await engine.pve.cluster_vms()
            vms = {"running": sum(1 for v in res if v.get("status") == "running"),
                   "total": len(res)}
        except Exception:
            vms = None
    return {
        "mode": engine.mode,
        "health": health,
        "resources": {
            "max_ram_gb": await settings_svc.get_setting(db, "resources.max_ram_gb", 48),
            "max_vcpus": await settings_svc.get_setting(db, "resources.max_vcpus", 16),
            "max_disk_gb": await settings_svc.get_setting(db, "resources.max_disk_gb", 500),
        },
        "node": node,
        "vms": vms,
    }


@router.get("/engine/resources")
async def engine_resources(db: AsyncSession = Depends(get_db),
                           _=Depends(get_current_user)):
    """Live host capacity → suggested budget. The UI fills the budget fields on
    click — never silently overwrites what the admin chose."""
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine — configure a real engine first"}
    try:
        node = await engine.pve.node_status()
    except Exception as e:
        return {"ok": False, "reason": f"node status failed: {e}"}
    mem = node.get("memory") or {}
    ram_total_gb = (mem.get("total") or 0) / 2**30
    ram_free_gb = ram_total_gb - (mem.get("used") or 0) / 2**30
    cores = int((node.get("cpuinfo") or {}).get("cpus") or 0)
    disk_free_gb = 0.0
    try:
        pools = await engine.pve.get(f"/nodes/{engine.pve.creds.node}/storage")
        for p in pools or []:
            if p.get("active") and "images" in (p.get("content") or ""):
                disk_free_gb = max(disk_free_gb, (p.get("avail") or 0) / 2**30)
    except Exception:
        pass
    suggested = {
        # keep ~15% host headroom + everything already in use (app VM, PVE, ludus)
        "max_ram_gb": max(2, int(ram_free_gb * 0.85)),
        "max_vcpus": max(2, cores),
        "max_disk_gb": max(60, int(disk_free_gb * 0.8)),
    }
    return {"ok": True, "ram_total_gb": round(ram_total_gb, 1),
            "ram_free_gb": round(ram_free_gb, 1), "cores": cores,
            "disk_free_gb": round(disk_free_gb, 1), "suggested": suggested}


# ---------- LLM endpoint discovery / test ----------

_LLM_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_TEST_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)


async def _llm_endpoint(db: AsyncSession, base_url: str | None,
                        api_key: str | None) -> tuple[str, str]:
    """Resolve endpoint creds — draft values from the request win; '********'
    (redacted echo) and empty fall back to stored secrets."""
    url = (base_url or "").strip() or await settings_svc.get_secret(db, "llm.base_url")
    url = url.rstrip("/")
    if not url:
        raise HTTPException(422, "llm.base_url not configured")
    key = api_key if (api_key and api_key != "********") else None
    if key is None:
        key = await settings_svc.get_secret(db, "llm.api_key")
    return url, key


@router.post("/llm/models")
async def llm_models(body: dict, db: AsyncSession = Depends(get_db),
                     _=Depends(get_current_user)):
    """Proxy GET {base_url}/models — OpenAI-compatible discovery. Tolerant:
    every endpoint flavor returns {data:[{id}]} but field coverage varies."""
    url, key = await _llm_endpoint(db, body.get("base_url"), body.get("api_key"))
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as c:
            r = await c.get(f"{url}/models", headers=headers)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"connection failed: {type(e).__name__}: {e}",
                "models": []}
    if r.status_code >= 400:
        return {"ok": False, "error": f"GET /models -> {r.status_code}: {r.text[:200]}",
                "models": []}
    try:
        data = r.json()
        ids = sorted({m["id"] for m in data.get("data", [])
                      if isinstance(m, dict) and m.get("id")})
    except (ValueError, AttributeError) as e:
        return {"ok": False, "error": f"malformed /models response: {e}", "models": []}
    return {"ok": True, "models": [{"id": i} for i in ids]}


@router.post("/llm/test")
async def llm_test(body: dict, db: AsyncSession = Depends(get_db),
                   _=Depends(get_current_user)):
    """Real inference probe — catches bad auth, missing model and unsupported
    vision payloads that a /models lookup alone would never see."""
    url, key = await _llm_endpoint(db, body.get("base_url"), body.get("api_key"))
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(422, "model required")
    kind = body.get("kind", "chat")
    content: list | str = "Reply with exactly: ok"
    if kind == "vision":
        content = [
            {"type": "text", "text": "What color dominates this image? One word."},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{_TEST_PNG}"}},
        ]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as c:
            r = await c.post(f"{url}/chat/completions", headers=headers, json={
                "model": model, "max_tokens": 64,
                "messages": [{"role": "user", "content": content}],
            })
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"connection failed: {type(e).__name__}: {e}"}
    latency_ms = int((time.monotonic() - started) * 1000)
    if r.status_code >= 400:
        return {"ok": False, "latency_ms": latency_ms,
                "error": f"{r.status_code}: {r.text[:300]}"}
    try:
        msg = r.json()["choices"][0]["message"]
        sample = (msg.get("content") or "")[:200]
        if not sample and (rc := msg.get("reasoning_content")):
            sample = f"(reasoning) {rc[:160]}"
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return {"ok": False, "latency_ms": latency_ms,
                "error": f"malformed response: {type(e).__name__}"}
    return {"ok": True, "latency_ms": latency_ms, "sample": sample.strip()}


# effort levels worth trying at any OpenAI-compatible endpoint — union of the
# LM Studio/Qwen set and OpenAI's reasoning_effort vocabulary
DEFAULT_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh"]


@router.post("/llm/reasoning-efforts")
async def llm_reasoning_efforts(body: dict, db: AsyncSession = Depends(get_db),
                                _=Depends(get_current_user)):
    """Probe the endpoint's real effort vocabulary by sending an invalid value —
    servers that validate reply with "Supported values: …" (LM Studio/Qwen do);
    everything else gets the union fallback."""
    url, key = await _llm_endpoint(db, body.get("base_url"), body.get("api_key"))
    model = ((body.get("model") or "").strip()
             or await settings_svc.get_secret(db, "llm.model"))
    if not model:
        return {"ok": False, "error": "model required", "efforts": DEFAULT_EFFORTS,
                "source": "fallback"}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as c:
            r = await c.post(f"{url}/chat/completions", headers=headers, json={
                "model": model, "max_tokens": 1, "reasoning_effort": "pentrain_probe",
                "messages": [{"role": "user", "content": "probe"}],
            })
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"connection failed: {type(e).__name__}: {e}",
                "efforts": DEFAULT_EFFORTS, "source": "fallback"}
    if r.status_code >= 400:
        m = re.search(r"supported values[^a-zA-Z]*([a-zA-Z,\s]+)", r.text, re.IGNORECASE)
        if m:
            efforts = [e for e in re.split(r"[,\s]+", m.group(1).strip())
                       if re.fullmatch(r"[a-z]+", e)]
            if efforts:
                return {"ok": True, "efforts": efforts, "source": "endpoint"}
    return {"ok": True, "efforts": DEFAULT_EFFORTS, "source": "fallback"}


@router.get("/llm/usage")
async def llm_usage(days: int = 7, db: AsyncSession = Depends(get_db),
                    _=Depends(get_current_user)):
    """Aggregated coach-LLM consumption for the stats page."""
    days = max(1, min(days, 90))
    since = date.today() - timedelta(days=days - 1)
    day_col = func.date(LlmUsage.ts)
    rows = (await db.execute(
        select(day_col.label("day"),
               func.count(LlmUsage.id).label("requests"),
               func.coalesce(func.sum(LlmUsage.total_tokens), 0).label("tokens"),
               func.coalesce(func.sum(LlmUsage.prompt_tokens), 0).label("prompt"),
               func.coalesce(func.sum(LlmUsage.completion_tokens), 0).label("completion"),
               func.coalesce(func.avg(LlmUsage.latency_ms), 0).label("avg_latency_ms"))
        .where(day_col >= since.isoformat())
        .group_by(day_col))).all()
    grouped = (await db.execute(
        select(LlmUsage.model.label("k"), LlmUsage.kind.label("kind"),
               func.count(LlmUsage.id).label("requests"),
               func.coalesce(func.sum(LlmUsage.total_tokens), 0).label("tokens"),
               func.coalesce(func.avg(LlmUsage.latency_ms), 0).label("lat"))
        .where(day_col >= since.isoformat())
        .group_by(LlmUsage.model, LlmUsage.kind))).all()
    by_model: dict[str, dict] = {}
    by_kind: list[dict] = []
    for r in grouped:
        m = by_model.setdefault(r.k or "(unknown)",
                                {"model": r.k or "(unknown)", "requests": 0, "tokens": 0})
        m["requests"] += r.requests
        m["tokens"] += r.tokens
        by_kind.append({"kind": r.kind, "model": r.k or "(unknown)",
                        "requests": r.requests, "tokens": r.tokens,
                        "avg_latency_ms": round(r.lat)})
    return {
        "days": [{"day": str(r.day), "requests": r.requests, "tokens": r.tokens,
                  "prompt": r.prompt, "completion": r.completion,
                  "avg_latency_ms": round(r.avg_latency_ms)} for r in rows],
        "by_model": sorted(by_model.values(), key=lambda m: -m["tokens"]),
        "by_kind": sorted(by_kind, key=lambda k: -k["tokens"]),
        "budget": await settings_svc.get_setting(db, "llm.daily_token_budget", 0),
    }


@router.get("/engine/metrics")
async def engine_metrics(timeframe: str = "hour",
                         db: AsyncSession = Depends(get_db),
                         _=Depends(get_current_user)):
    """Proxy PVE node rrddata — host cpu/mem/net/io time series for /stats."""
    if timeframe not in ("hour", "day", "week", "month"):
        timeframe = "hour"
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine — no host metrics", "rows": []}
    try:
        rows = await engine.pve.node_rrddata(timeframe)
    except Exception as e:
        return {"ok": False, "reason": f"rrddata failed: {e}", "rows": []}
    keep = ("time", "cpu", "maxcpu", "loadavg", "memused", "memtotal",
            "memavailable", "netin", "netout", "iowait", "swapused",
            "roottotal", "rootused")
    return {"ok": True, "timeframe": timeframe,
            "rows": [{k: r[k] for k in keep if k in r} for r in rows]}


@router.get("/engine/storage")
async def engine_storage(timeframe: str | None = None,
                         db: AsyncSession = Depends(get_db),
                         _=Depends(get_current_user)):
    """Storage pools with usage; ?timeframe=hour|day|week adds a per-pool
    usage trend (storage rrddata) — errors stay isolated per pool."""
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine", "pools": []}
    try:
        pools = await engine.pve.storage_pools()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200], "pools": []}
    out = []
    for p in pools:
        item = {k: p.get(k) for k in
                ("storage", "type", "content", "total", "used", "avail", "active", "shared")}
        if timeframe in ("hour", "day", "week") and p.get("active"):
            try:
                rows = await engine.pve.storage_rrddata(p["storage"], timeframe)
                item["trend"] = [{k: r[k] for k in ("time", "used", "total") if k in r}
                                 for r in rows]
            except Exception as e:
                item["trend_error"] = str(e)[:120]
        out.append(item)
    return {"ok": True, "pools": out}


def _parse_smart(smart: dict) -> dict:
    """Normalize PVE SMART output — NVMe flat fields vs. ATA attribute table."""
    out: dict = {}
    # NVMe/SCSI flat shape
    if isinstance(smart.get("temperature"), (int, float)):
        out["temp_c"] = smart["temperature"]
    if isinstance(smart.get("power_on_hours"), (int, float)):
        out["power_on_hours"] = smart["power_on_hours"]
    if isinstance(smart.get("percentage_used"), (int, float)):
        out["wearout_pct"] = smart["percentage_used"]
    # ATA attribute table
    for a in smart.get("attributes") or []:
        name = str(a.get("name") or "").lower()
        raw = a.get("raw")
        if isinstance(raw, dict):
            raw = raw.get("value")
        if name in ("temperature_celsius", "airflow_temperature_cel", "temperature") \
                and "temp_c" not in out:
            out["temp_c"] = raw
        elif name == "power_on_hours" and "power_on_hours" not in out:
            out["power_on_hours"] = raw
        elif name == "wear_leveling_count" and "wearout_pct" not in out:
            # raw is remaining-life % on most SSDs
            with contextlib.suppress(TypeError, ValueError):
                out["wearout_pct"] = 100 - int(raw)
        elif name == "reallocated_sector_ct":
            out["reallocated"] = raw
    if smart.get("health"):
        out["smart_health"] = smart["health"]
    return out


@router.get("/engine/disks")
async def engine_disks(db: AsyncSession = Depends(get_db),
                       _=Depends(get_current_user)):
    """Physical disk inventory + SMART health/temperature/wearout per disk."""
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine", "disks": []}
    try:
        disks = await engine.pve.disks_list()
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200], "disks": []}
    out = []
    for d in disks:
        dev = d.get("devpath") or d.get("dev")
        item = {"dev": dev, "model": d.get("model"), "serial": d.get("serial"),
                "size_gb": round((d.get("size") or 0) / 2**30, 1),
                "type": d.get("type"), "health": d.get("health"),
                "wearout_pct": d.get("wearout")}
        if dev:
            try:
                smart = await engine.pve.disk_smart(dev)
                for k, v in _parse_smart(smart).items():
                    # disks/list wearout wins over the smart-derived guess
                    if k == "wearout_pct" and item.get("wearout_pct") is not None:
                        continue
                    item[k] = v
            except Exception as e:
                item["smart_error"] = str(e)[:120]
        out.append(item)
    return {"ok": True, "disks": out}


@router.get("/engine/hoststats")
async def engine_hoststats(db: AsyncSession = Depends(get_db),
                           _=Depends(get_current_user)):
    """CPU temps / GPU / fans from the optional pentrain-hoststats agent on the
    engine host — shared service cache so refreshes don't hammer it."""
    engine = await get_engine(db)
    if engine.mode == "mock":
        return {"ok": False, "reason": "mock engine"}
    return await hoststats_svc.fetch(db, engine, ttl_s=30)


@router.get("/stats/activity")
async def stats_activity(days: int = 30, db: AsyncSession = Depends(get_db),
                         _=Depends(get_current_user)):
    """Training-side stats from our own tables — deploy durations, daily
    attempts, score history and the assistance mix."""
    days = max(1, min(days, 90))
    since = date.today() - timedelta(days=days - 1)
    since_dt = datetime(since.year, since.month, since.day)

    deploy_rows = (await db.execute(
        select(Session.created_at, Session.ready_at, Session.state)
        .where(Session.created_at >= since_dt))).all()
    durations = [int((r.ready_at - r.created_at).total_seconds())
                 for r in deploy_rows if r.ready_at]
    deploys = {"sessions": len(deploy_rows), "ready": len(durations),
               "failed": sum(1 for r in deploy_rows
                             if r.state == SessionState.FAILED.value),
               "avg_s": round(sum(durations) / len(durations)) if durations else 0,
               "last_s": durations[-1] if durations else 0}

    att_rows = (await db.execute(
        select(Attempt).where(func.date(Attempt.created_at) >= since.isoformat())
        .order_by(Attempt.created_at))).scalars().all()
    per_day: dict[str, dict] = {}
    for a in att_rows:
        d = a.created_at.date().isoformat()
        v = per_day.setdefault(d, {"day": d, "count": 0, "score_sum": 0})
        v["count"] += 1
        v["score_sum"] += a.score or 0
    attempts = [{"day": v["day"], "count": v["count"],
                 "avg_score": round(v["score_sum"] / v["count"])}
                for v in sorted(per_day.values(), key=lambda v: v["day"])]
    scores = [{"quest_id": a.quest_id, "score": a.score,
               "ts": a.created_at.isoformat()} for a in att_rows[-30:]]

    aids = {k: 0 for k in ("hints", "coach_msgs", "coach_nudges",
                           "sheet", "chat", "takeovers", "solo", "total")}
    for a in (await db.execute(select(Attempt))).scalars().all():
        as_ = a.assistance or {}
        # legacy fallback — rows predate the assistance snapshot field
        vals = {"hints": as_.get("hints") or a.hints_used or 0,
                "takeovers": as_.get("takeovers") or a.coach_interventions or 0,
                "coach_msgs": as_.get("coach_msgs") or 0,
                "coach_nudges": as_.get("coach_nudges") or 0,
                "sheet": as_.get("sheet") or 0,
                "chat": as_.get("chat") or 0}
        used = any(vals.values())
        for k, v in vals.items():
            aids[k] += int(v)
        aids["solo" if not used else "total"] += 1
    return {"ok": True, "deploys": deploys, "attempts": attempts,
            "scores": scores, "aids": aids}


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


@coach_router.get("/active-sessions")
async def coach_active_sessions(db: AsyncSession = Depends(get_db)):
    """Sessions the coach should attach to (post-restart sweep): anything
    ready/active — idle sessions emit no events and would stay orphaned."""
    rows = (await db.execute(
        select(Session.id, Session.state).where(
            Session.state.in_([SessionState.READY.value,
                               SessionState.ACTIVE.value])))).all()
    return [{"id": r[0], "state": r[1]} for r in rows]


@coach_router.post("/message")
async def coach_message(body: CoachMessageIn, db: AsyncSession = Depends(get_db)):
    msg = await coach_bridge.post_message(
        db, body.session_id, "coach", body.kind, body.content, body.meta)
    return {"id": msg.id}


@coach_router.post("/stream")
async def coach_stream(body: CoachStreamIn):
    """Relay an in-progress draft to the session UI. Pure bus event — nothing
    is persisted; the final send_chat call creates the real message. Sticky
    while streaming so a page reload re-hydrates the draft bubble."""
    await publish_session(body.session_id, "coach_stream", {
        "draft_id": body.draft_id, "content": body.content,
        "reasoning": body.reasoning,
        "done": body.done, "kind": body.kind},
        sticky=not body.done)
    return {"ok": True}


@coach_router.post("/activity")
async def coach_activity(body: CoachActivityIn):
    """Live 'the coach is doing X' indicator for the session UI — ephemeral
    bus event like /stream, cleared by a follow-up with active=false."""
    await publish_session(body.session_id, "coach_activity",
                          {"active": body.active, "text": body.text},
                          sticky=body.active)
    return {"ok": True}


@coach_router.post("/suggest")
async def coach_suggest(body: CoachSuggestIn, db: AsyncSession = Depends(get_db)):
    a = await coach_bridge.suggest_command(db, body.session_id, body.command, body.why)
    return {"id": a.id, "status": a.status}


@coach_router.post("/exec")
async def coach_exec(body: CoachExecIn, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.exec_in_kali(db, body.session_id, body.command)


@coach_router.post("/type")
async def coach_type(body: CoachTypeIn, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.type_in_pane(db, body.session_id, body.text)


@coach_router.post("/flag")
async def coach_flag(body: CoachFlagIn, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.submit_flag(db, body.session_id, body.value)


@coach_router.post("/flag-check")
async def coach_flag_check(body: CoachFlagCheckIn, db: AsyncSession = Depends(get_db)):
    return await coach_bridge.check_flag(db, body.session_id, body.flag_key)


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
            "reasoning": await settings_svc.get_setting(db, "llm.reasoning", True),
            "reasoning_effort": await settings_svc.get_setting(db, "llm.reasoning_effort", "medium"),
            "use_tools": await settings_svc.get_setting(db, "llm.use_tools", True),
        },
        "coach": {
            "enabled": await settings_svc.get_setting(db, "coach.enabled", True),
            "verbosity": await settings_svc.get_setting(db, "coach.verbosity", "normal"),
            "personality": await settings_svc.get_setting(db, "coach.personality", "mentor"),
            "reflect_interval_s": await settings_svc.get_setting(db, "coach.reflect_interval_s", 60),
            "nudge_after_s": await settings_svc.get_setting(db, "coach.nudge_after_s", 480),
            "hint_after_s": await settings_svc.get_setting(db, "coach.hint_after_s", 900),
            "action_budget": await settings_svc.get_setting(db, "coach.action_budget", 50),
            "takeover_pace_s": await settings_svc.get_setting(db, "coach.takeover_pace_s", 10),
            "takeover_chain_max": await settings_svc.get_setting(db, "coach.takeover_chain_max", 12),
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


@coach_router.post("/llm-usage", status_code=204)
async def coach_llm_usage(body: dict, db: AsyncSession = Depends(get_db)):
    """Coach reports per-request token/latency for the stats page — fire-and-forget."""
    db.add(LlmUsage(
        session_id=body.get("session_id") or None,
        model=str(body.get("model") or "")[:160],
        kind=str(body.get("kind") or "chat")[:24],
        prompt_tokens=int(body.get("prompt_tokens") or 0),
        completion_tokens=int(body.get("completion_tokens") or 0),
        total_tokens=int(body.get("total_tokens") or 0),
        latency_ms=int(body.get("latency_ms") or 0),
    ))
    await db.commit()


# ---------- kali template builder ----------

@router.get("/admin/console/vm/{vmid}/ticket")
async def admin_vm_console_ticket(vmid: int, db: AsyncSession = Depends(get_db),
                                  _=Depends(get_current_user)):
    """VNC ticket for a standalone VM — pairs with WS /api/console/vm/{vmid}."""
    result = await console_svc.issue_vm_ticket(db, vmid)
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result



@router.get("/admin/kali-template/status")
async def kali_template_status(db: AsyncSession = Depends(get_db),
                               _=Depends(get_current_user)):
    from ..services import kalibuild
    engine = await get_engine(db)
    return await kalibuild.status(db, engine)


@router.get("/admin/kali-template/templates")
async def kali_template_list(db: AsyncSession = Depends(get_db),
                             _=Depends(get_current_user)):
    from ..services import kalibuild
    engine = await get_engine(db)
    return {"templates": await kalibuild.list_templates(db, engine)}


@router.post("/admin/kali-template/build", status_code=201)
async def kali_template_build(body: dict, db: AsyncSession = Depends(get_db),
                              _=Depends(get_current_user)):
    from ..services import kalibuild
    engine = await get_engine(db)
    base = str(body.get("base_template") or
               await settings_svc.get_setting(db, "engine.kali_template", "")
               or "kali-x64-desktop-template")
    try:
        return await kalibuild.start_build(db, engine, base,
                                           name=body.get("name") or None)
    except kalibuild.BuildError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/admin/kali-template/finalize")
async def kali_template_finalize(body: dict, db: AsyncSession = Depends(get_db),
                                 _=Depends(get_current_user)):
    from ..services import kalibuild
    engine = await get_engine(db)
    try:
        return await kalibuild.finalize(db, engine,
                                        template_name=body.get("template_name") or None)
    except kalibuild.BuildError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/admin/kali-template/abandon")
async def kali_template_abandon(db: AsyncSession = Depends(get_db),
                                _=Depends(get_current_user)):
    from ..services import kalibuild
    engine = await get_engine(db)
    try:
        return await kalibuild.abandon(db, engine)
    except kalibuild.BuildError as e:
        raise HTTPException(422, str(e)) from e
