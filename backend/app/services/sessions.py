"""Session lifecycle: QUEUED → DEPLOYING → READY → ACTIVE → SOLVED|ABORTED|FAILED
                                                      ↘ RESETTING → READY

One active session at a time (v1). Deploy/reset run as background asyncio tasks;
every transition persists to DB and broadcasts on the event bus so UI + coach
survive restarts and stay in sync.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_factory
from ..models.domain import (
    Attempt,
    CoachAction,
    CoachMessage,
    Flag,
    HintUse,
    Quest,
    Session,
    SessionState,
)
from ..ranges.base import RangeState
from ..ranges.ludus import SNAP_POST_DEPLOY
from . import coach_bridge
from . import flags as flags_svc
from . import kali_net as kali_net_svc
from . import scoring as scoring_svc
from . import settings as settings_svc
from .engine import get_engine
from .events import bus, ephemeral_clear, publish_session
from .flags import new_seed, new_telemetry_token

log = structlog.get_logger(__name__)

_tasks: dict[int, asyncio.Task] = {}
_create_lock = asyncio.Lock()  # serializes active-check + insert
POLL_S = 10          # status poll interval during deploy (patched in tests)


class SessionError(RuntimeError):
    pass


# ---------------- helpers ----------------

async def _broadcast(session_id: int, type_: str, data: dict | None = None) -> None:
    await bus.publish(f"session.{session_id}", {
        "type": type_, "session_id": session_id, "data": data or {}})


async def _set_state(db: AsyncSession, session: Session, state: SessionState,
                     **fields) -> None:
    session.state = state.value
    for k, v in fields.items():
        setattr(session, k, v)
    await db.commit()
    await _broadcast(session.id, "state", {"state": state.value, **{k: str(v) for k, v in fields.items() if v is not None}})
    if state in (SessionState.ABORTED, SessionState.FAILED, SessionState.SOLVED):
        # terminal — no replayed drafts/activity should outlive the session
        ephemeral_clear(session.id)


async def _append_log(db: AsyncSession, session: Session, line: str) -> None:
    session.deploy_log = (session.deploy_log or "") + line + "\n"
    await db.commit()
    await _broadcast(session.id, "deploy_log", {"line": line})


def compile_topology(quest: Quest, kali_template: str | None = None) -> dict:
    """quest.topology → Ludus range config (subset of Ludus schema we need).

    `kali_template` (engine.kali_template setting) overrides the per-quest
    template globally — a user's custom build is meant to apply everywhere.

    Every VM carries ram_min_gb alongside ram_gb — Ludus maps it to Proxmox
    memory ballooning, so a range squeezed onto a small host still boots and
    shrinks under pressure instead of being refused outright.
    """
    topo = quest.topology or {}
    vms: list[dict] = []
    kali = topo.get("kali") or {}
    vms.append({
        "vm_name": "{{ range_id }}-kali",
        "hostname": "{{ range_id }}-KALI",
        "template": kali_template or kali.get("template", "kali-x64-desktop-template"),
        "vlan": 10,
        "ip_last_octet": 5,
        "ram_gb": kali.get("ram_gb", 6),
        "ram_min_gb": kali.get("ram_min_gb") or 3,
        "cpus": kali.get("cpus", 4),
        "linux": True,
        "roles": ["pentrain_kali_agent"],
    })
    for i, v in enumerate(topo.get("vms") or []):
        ram_gb = v.get("ram_gb", 4)
        entry = {
            "vm_name": f"{{{{ range_id }}}}-{v['name']}",
            "hostname": f"{{{{ range_id }}}}-{v['name'].upper()[:14]}",
            "template": v["template"],
            "vlan": v.get("vlan", 10),
            "ip_last_octet": v.get("ip_last_octet", 20 + i),
            "ram_gb": ram_gb,
            "ram_min_gb": v.get("ram_min_gb") or max(1, ram_gb // 2),
            "cpus": v.get("cpus", 2),
            "linux": v.get("linux", True),
        }
        if v.get("windows"):
            entry["windows"] = dict(v["windows"])
            entry["linux"] = False
        if v.get("domain"):
            entry["domain"] = v["domain"]
        if v.get("gpos"):
            # Ludus expects gpos under windows.gpos — VmSpec keeps them
            # top-level for yaml ergonomics
            entry.setdefault("windows", {})["gpos"] = v["gpos"]
            entry["linux"] = False
        if v.get("roles"):
            entry["roles"] = v["roles"]
        vms.append(entry)
    # Ludus auto-adds the router VM (default debian-13 template, 2G). We pin
    # debian-12 — the server template every linux quest already requires —
    # and size it explicitly so it balloons on small hosts too.
    router = {"template": "debian-12-x64-server-template",
              "ram_gb": 2, "ram_min_gb": 1,
              **(topo.get("router") or {})}
    return {"ludus": vms, "router": router}


async def check_unlock(db: AsyncSession, quest: Quest) -> tuple[bool, str]:
    """Adaptive unlock: resource budget + tier progression."""
    req = quest.requirements or {}
    for key, req_key, unit in (
        ("resources.max_ram_gb", "min_ram_gb", "G RAM"),
        ("resources.max_vcpus", "min_vcpus", " vCPU"),
        ("resources.max_disk_gb", "min_disk_gb", "G disk"),
    ):
        try:
            budget = int(await settings_svc.get_setting(db, key, 0) or 0)
            need = int(req.get(req_key, 0) or 0)
        except (TypeError, ValueError):  # a bad setting shouldn't brick unlock checks
            continue
        if need > budget:
            return False, f"requires {need}{unit} (budget {budget})"
    if quest.tier > 1 or quest.exam:
        solved_ids = await solved_quest_ids(db)
    if quest.tier > 1:
        # any non-exam quest at the previous tier unlocks this one —
        # exams are capstones, not stepping stones
        prevs = (await db.execute(
            select(Quest.id).where(Quest.track_slug == quest.track_slug,
                                   Quest.tier == quest.tier - 1,
                                   Quest.exam.is_not(True)))).scalars().all()
        if prevs and not any(p in solved_ids for p in prevs):
            return False, f"solve a tier {quest.tier - 1} quest in this track first"
    if quest.exam:
        # capstone gate: every non-exam quest at this tier must be solved
        peers = (await db.execute(
            select(Quest.id).where(Quest.track_slug == quest.track_slug,
                                   Quest.tier == quest.tier,
                                   Quest.exam.is_not(True)))).scalars().all()
        missing = [p for p in peers if p not in solved_ids]
        if missing:
            done = len(peers) - len(missing)
            return False, (f"exam: solve all tier {quest.tier} quests first "
                           f"({done}/{len(peers)} done)")
    return True, ""


async def active_session(db: AsyncSession) -> Session | None:
    return (await db.execute(
        select(Session).where(Session.state.in_([
            SessionState.QUEUED.value, SessionState.DEPLOYING.value,
            SessionState.READY.value, SessionState.ACTIVE.value,
            SessionState.RESETTING.value]))
        .order_by(Session.id.desc()).limit(1))).scalar_one_or_none()


# ---------------- lifecycle ----------------

async def create_session(db: AsyncSession, quest_id: str) -> Session:
    async with _create_lock:  # one active session at a time — no TOCTOU
        quest = await db.get(Quest, quest_id)
        if not quest or not quest.active:
            raise SessionError(f"quest {quest_id} not found/inactive")
        ok, reason = await check_unlock(db, quest)
        if not ok:
            raise SessionError(f"quest locked: {reason}")
        if await active_session(db):
            raise SessionError("another session is active — abort it first")
        autonomy = int(await settings_svc.get_setting(db, "coach.default_autonomy", 2))
        coach_enabled = bool(await settings_svc.get_setting(db, "coach.enabled", True))
        session = Session(
            quest_id=quest_id, state=SessionState.QUEUED.value,
            flag_seed=new_seed(), telemetry_token=new_telemetry_token(),
            autonomy_level=autonomy, coach_enabled=coach_enabled,
        )
        db.add(session)
        await db.commit()
    await _broadcast(session.id, "state", {"state": session.state})
    _tasks[session.id] = asyncio.create_task(_deploy(session.id))
    return session


async def _deploy(session_id: int) -> None:
    try:
        async with session_factory()() as db:
            session = await db.get(Session, session_id)
            if not session:
                return
            quest = await db.get(Quest, session.quest_id)
            try:
                engine = await get_engine(db)
                await _set_state(db, session, SessionState.DEPLOYING)
                await _append_log(db, session, "[pentrain] compiling topology → ludus config")
                config = compile_topology(
                    quest,
                    kali_template=await settings_svc.get_setting(
                        db, "engine.kali_template", "") or None)
                await _append_log(db, session, yaml.safe_dump(config, sort_keys=False).rstrip())
                session.range_id = await engine.provider.deploy_range(f"quest-{quest.id}", config)
                await db.commit()

                st = await _watch_range(db, engine, session)
                await _finalize(db, engine, session, quest, st)
            except Exception as e:
                await log.aexception("deploy failed", session_id=session_id)
                await _set_state(db, session, SessionState.FAILED, error=str(e))
    finally:
        _tasks.pop(session_id, None)


async def _watch_range(db: AsyncSession, engine, session: Session,
                       seen_log_seed: str = ""):
    """Poll ludus until the range is RUNNING (max ~45 min for big AD labs).

    `seen_log_seed` lets the resume path skip lines already persisted before a
    backend restart, so the deploy log continues instead of repeating. Status
    failures are tolerated — a flaky API must not kill a 30-minute deploy."""
    seen_log = seen_log_seed
    consec_errors = 0
    for _ in range(45 * 6):
        try:
            st = await engine.provider.status(session.range_id or None)
        except Exception as e:
            consec_errors += 1
            if consec_errors >= 6:
                raise SessionError(f"range status unreachable: {e}") from e
            await asyncio.sleep(POLL_S)
            continue
        consec_errors = 0
        tail = st.log_tail or ""
        if tail != seen_log:
            new = tail[len(seen_log):] if tail.startswith(seen_log) else "\n" + tail
            seen_log = tail
            for line in new.strip("\n").splitlines():
                if line.strip():
                    await _append_log(db, session, line)
        if st.state == RangeState.RUNNING:
            return st
        if st.state == RangeState.FAILED:
            raise SessionError("range deploy failed — see deploy log")
        await asyncio.sleep(POLL_S)
    raise SessionError("deploy timed out")


async def _finalize(db: AsyncSession, engine, session: Session,
                    quest: Quest, st) -> None:
    """RUNNING range → ready session. Idempotent — the resume path may re-run
    telemetry/flags/snapshot on a range that already passed through here."""
    await db.commit()
    kali = next((v for v in st.vms if v.role == "kali" or "kali" in v.name.lower()), None)
    session.kali_vmid = kali.vmid if kali else None
    # map short names → vmid (ludus names are "<rid>-<name>")
    session.target_vmids = {
        (v.name.split("-", 1)[-1] if "-" in v.name else v.name): v.vmid
        for v in st.vms if v is not kali and v.vmid}
    await _append_log(db, session, f"[pentrain] range RUNNING — kali vmid={session.kali_vmid}")

    # telemetry config on kali
    if session.kali_vmid:
        await _configure_kali_telemetry(db, engine, session)

    # dynamic flags
    quest_flags = (await db.execute(
        select(Flag).where(Flag.quest_id == quest.id))).scalars().all()
    await flags_svc.create_expected_flags(db, session, quest_flags)
    for line in await flags_svc.inject_flags(db, engine, session, quest_flags):
        await _append_log(db, session, f"[pentrain] {line}")

    # kali wan uplink — BEFORE the snapshot so soft reset keeps the net1
    # config. Non-fatal: a missing DHCP lease must not sink the deploy.
    want_net = bool(session.kali_internet) or bool(
        await settings_svc.get_setting(db, "kali.internet_default", False))
    if want_net and session.kali_vmid:
        try:
            res = await kali_net_svc.apply_kali_internet(
                engine, session.kali_vmid,
                await settings_svc.get_setting(db, "engine.kali_wan_bridge", "vmbr0"),
                kali_net_svc.target_names_for(quest))
            session.kali_internet = True
            await db.commit()
            detail = f"{res.get('ip','?')} via {res.get('iface','?')}" if res.get("ip") else "mock"
            await _append_log(db, session, f"[pentrain] kali internet on ({detail})")
        except Exception as e:
            await _append_log(db, session, f"[pentrain] kali internet failed: {e}")

    # internet isolation + restore point (allow the app/telemetry endpoint)
    if bool(await settings_svc.get_setting(db, "engine.testing_mode", True)):
        allow = await settings_svc.get_setting(db, "engine.testing_allow", [])
        await engine.provider.testing_mode(True, allow_ips=allow or None)
    await _append_log(db, session, "[pentrain] snapshotting range (soft-reset point)")
    await engine.provider.snapshot_all(session.range_id or None, SNAP_POST_DEPLOY)

    await _set_state(db, session, SessionState.READY,
                     ready_at=datetime.now(UTC).replace(tzinfo=None))


async def resume_inflight() -> int:
    """Reattach to sessions whose deploy/reset task died with the process.

    Ludus deploys server-side — a backend restart orphans the watcher, not the
    range. Called once from the app lifespan after packs are synced."""
    async with session_factory()() as db:
        rows = (await db.execute(
            select(Session).where(Session.state.in_([
                SessionState.QUEUED.value, SessionState.DEPLOYING.value,
                SessionState.RESETTING.value])))).scalars().all()
        ids = [s.id for s in rows]
    for sid in ids:
        _tasks[sid] = asyncio.create_task(_resume(sid))
    if ids:
        await log.ainfo("inflight sessions resumed", sessions=ids)
    return len(ids)


async def _resume(session_id: int) -> None:
    """Decide per persisted state + live range status how to continue a
    session whose in-process task was lost (restart, crash)."""
    try:
        async with session_factory()() as db:
            session = await db.get(Session, session_id)
            if not session:
                return
            quest = await db.get(Quest, session.quest_id)
            try:
                engine = await get_engine(db)
                try:
                    st = await engine.provider.status(session.range_id or None)
                except Exception as e:
                    # engine unreachable at boot — leave the state alone so the
                    # next restart can try again instead of failing a live range
                    await log.awarning("resume status probe failed — leaving state",
                                       session_id=session_id, error=str(e))
                    return
                await _append_log(
                    db, session,
                    f"[pentrain] backend restarted — resuming (range {st.state.value})")
                if session.state == SessionState.QUEUED.value or st.state == RangeState.ABSENT:
                    await _deploy(session_id)
                    return
                if st.state == RangeState.FAILED:
                    await _set_state(db, session, SessionState.FAILED,
                                     error="deploy failed while backend was down")
                    return
                if session.state == SessionState.RESETTING.value and st.state == RangeState.RUNNING:
                    await _reset(session_id, hard=True)
                    return
                if st.state == RangeState.DEPLOYING:
                    st = await _watch_range(db, engine, session,
                                            seen_log_seed=st.log_tail or "")
                if st.state == RangeState.RUNNING:
                    await _finalize(db, engine, session, quest, st)
            except Exception as e:
                await log.aexception("resume failed", session_id=session_id)
                await _set_state(db, session, SessionState.FAILED, error=str(e))
    finally:
        _tasks.pop(session_id, None)


async def activate(db: AsyncSession, session_id: int) -> Session:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.READY.value:
        raise SessionError("session not ready")
    await _set_state(db, session, SessionState.ACTIVE,
                     started_at=datetime.now(UTC).replace(tzinfo=None))
    db.add(CoachMessage(session_id=session.id, role="system", kind="chat",
                        content=f"Session started on quest {session.quest_id}."))
    await db.commit()
    return session


async def submit_flag(db: AsyncSession, session_id: int, value: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.ACTIVE.value:
        raise SessionError("session not active")
    engine = await get_engine(db)
    result = await flags_svc.submit_flag(db, engine, session, value)
    await _broadcast(session_id, "flag", result)
    if result["all_solved"]:
        await _set_state(db, session, SessionState.SOLVED,
                         ended_at=datetime.now(UTC).replace(tzinfo=None))
        attempt = await scoring_svc.finalize_attempt(db, session)
        await _broadcast(session_id, "solved", {"score": attempt.score, "attempt_id": attempt.id})
    return result


async def check_flag(db: AsyncSession, session_id: int, flag_key: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state != SessionState.ACTIVE.value:
        raise SessionError("session not active")
    engine = await get_engine(db)
    result = await flags_svc.check_and_record_flag(db, engine, session, flag_key)
    if err := result.pop("error", None):
        raise SessionError(err)
    await _broadcast(session_id, "flag", result)
    if result["all_solved"]:
        await _set_state(db, session, SessionState.SOLVED,
                         ended_at=datetime.now(UTC).replace(tzinfo=None))
        attempt = await scoring_svc.finalize_attempt(db, session)
        await _broadcast(session_id, "solved", {"score": attempt.score, "attempt_id": attempt.id})
    return result


async def use_hint(db: AsyncSession, session_id: int, hint_id: str) -> dict:
    session = await db.get(Session, session_id)
    if not session or session.state not in (SessionState.ACTIVE.value, SessionState.READY.value):
        raise SessionError("no active session")
    quest = await db.get(Quest, session.quest_id)
    hint = next((h for h in ((quest.hints_cfg if quest else []) or []) if h.get("id") == hint_id), None)
    if not hint:
        raise SessionError(f"unknown hint {hint_id}")
    db.add(HintUse(session_id=session_id, hint_id=hint_id, cost=int(hint.get("cost", 0))))
    await db.commit()
    await _broadcast(session_id, "hint", {"hint_id": hint_id, "cost": hint.get("cost")})
    return hint


async def reset(db: AsyncSession, session_id: int, *, hard: bool = False) -> Session:
    session = await db.get(Session, session_id)
    if not session or session.state in (SessionState.ABORTED.value, SessionState.FAILED.value):
        raise SessionError("session not resettable")
    await _set_state(db, session, SessionState.RESETTING)
    _tasks[session.id] = asyncio.create_task(_reset(session.id, hard))
    return session


async def _reset(session_id: int, hard: bool) -> None:
    async with session_factory()() as db:
        session = await db.get(Session, session_id)
        quest = await db.get(Quest, session.quest_id) if session else None
        try:
            engine = await get_engine(db)
            if hard:
                await _append_log(db, session, "[pentrain] hard reset: destroy + redeploy")
                await engine.provider.destroy_range(session.range_id)
                await _set_state(db, session, SessionState.QUEUED)
                _tasks[session_id] = asyncio.create_task(_deploy(session_id))
                return
            await _append_log(db, session, "[pentrain] soft reset: snapshot rollback")
            await engine.provider.rollback_all(session.range_id, SNAP_POST_DEPLOY)
            # rollback restores the snapshot's VM config — re-align net1 with
            # the session flag (toggle may have changed after the snapshot)
            if session.kali_vmid:
                try:
                    if session.kali_internet:
                        await kali_net_svc.apply_kali_internet(
                            engine, session.kali_vmid,
                            await settings_svc.get_setting(
                                db, "engine.kali_wan_bridge", "vmbr0"),
                            kali_net_svc.target_names_for(quest) if quest else [])
                    else:
                        await kali_net_svc.remove_kali_internet(
                            engine, session.kali_vmid)
                except Exception as e:
                    await log.awarning("kali internet re-apply failed", error=str(e)[:150])
            # re-randomize flags (old secrets are gone after rollback)
            session.flag_seed = new_seed()
            session.telemetry_token = new_telemetry_token()
            await db.commit()
            if session.kali_vmid:
                await _configure_kali_telemetry(db, engine, session)
            quest_flags = (await db.execute(
                select(Flag).where(Flag.quest_id == quest.id))).scalars().all()
            await flags_svc.create_expected_flags(db, session, quest_flags)
            for line in await flags_svc.inject_flags(db, engine, session, quest_flags):
                await _append_log(db, session, f"[pentrain] {line}")
            await _set_state(db, session, SessionState.READY)
        except Exception as e:
            await log.aexception("reset failed", session_id=session_id)
            await _set_state(db, session, SessionState.FAILED, error=str(e))


async def _configure_kali_telemetry(db: AsyncSession, engine, session: Session) -> None:
    """(Re)write telemetried.conf on the session's Kali and restart the agent."""
    api_url = await settings_svc.get_setting(db, "platform.api_url", "http://pentrain-app:8000")
    conf = f"TOKEN={session.telemetry_token}\nSESSION={session.id}\nAPI={api_url}\n"
    try:
        await engine.pve.agent_write_file(session.kali_vmid, "/etc/pentrain/telemetried.conf", conf)
        await engine.pve.agent_exec_sh(
            session.kali_vmid, "systemctl restart pentrain-telemetried || true")
    except Exception as e:
        await _append_log(db, session, f"[pentrain] telemetry setup warn: {e}")


async def solved_quest_ids(db: AsyncSession) -> set[str]:
    """Quests that were ever fully solved. Anchored on finalized Attempts
    (created only on all_solved), NOT session.state — abort() legitimately
    tears down a solved session's range and must not erase progression."""
    return {r[0] for r in (await db.execute(select(Attempt.quest_id).distinct())).all()}


async def abort(db: AsyncSession, session_id: int) -> Session:
    session = await db.get(Session, session_id)
    if not session:
        raise SessionError("no session")
    task = _tasks.get(session_id)
    if task and not task.done():
        task.cancel()
    try:
        engine = await get_engine(db)
        await engine.provider.destroy_range(session.range_id)
    except Exception as e:
        await log.awarning("destroy failed", error=str(e))
    await _set_state(db, session, SessionState.ABORTED,
                     ended_at=datetime.now(UTC).replace(tzinfo=None))
    return session


async def suggest_command_confirm(db: AsyncSession, session_id: int, action_id: int,
                                  accept: bool) -> CoachAction:
    """Copilot (L3): user confirms/rejects a coach-suggested command."""
    action = await db.get(CoachAction, action_id)
    if not action or action.session_id != session_id:
        raise SessionError("action not found")
    if action.status != "pending":
        raise SessionError("action already resolved")
    session = await db.get(Session, session_id)
    if accept and (not session
                   or session.state not in (SessionState.ACTIVE.value, SessionState.READY.value)):
        raise SessionError("session not active")
    if accept:
        engine = await get_engine(db)
        cmd = action.args.get("command", "")
        try:
            # the confirmed command can run for a while — surface it in the UI
            await publish_session(session_id, "coach_activity", {
                "active": True,
                "text": f"executing confirmed `{cmd[:110]}`"}, sticky=True)
            # user-approved commands run visibly in the coach tmux as well
            res = await coach_bridge.exec_visible_in_kali(
                engine, session.kali_vmid, cmd, session_id=session_id) \
                if session.kali_vmid else {"out": "", "err": "no kali vmid", "exitcode": 1}
            action.result = res
            action.status = "confirmed"
            # surface the output in chat like a coach-executed command —
            # a confirmed suggestion that only says "executed" teaches nothing
            out = (res.get("out") or res.get("err") or "")[:500]
            note = ("\n\n*(typed live in the `pentrain-coach` tmux)*"
                    if res.get("visible") else "")
            await coach_bridge.post_message(
                db, session_id, "coach", "action_report",
                f"Executed (your confirmation): `{cmd}`\n```\n{out}\n```{note}")
        except Exception as e:
            action.result = {"error": str(e)}
            action.status = "error"
        finally:
            await publish_session(session_id, "coach_activity",
                                  {"active": False, "text": ""})
    else:
        action.status = "rejected"
    await db.commit()
    # mark the suggestion message resolved so the UI state survives reloads
    msg = (await db.execute(
        select(CoachMessage).where(
            CoachMessage.session_id == session_id,
            CoachMessage.kind == "suggestion",
            CoachMessage.meta["action_id"].as_integer() == action_id))).scalar_one_or_none()
    if msg:
        msg.meta = {**(msg.meta or {}), "resolved": action.status}
        await db.commit()
    await _broadcast(session_id, "coach_action", {"id": action.id, "status": action.status})
    return action
