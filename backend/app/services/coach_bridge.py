"""Coach bridge: internal API surface consumed by the coach service.

The coach is a separate container; it calls these functions via HTTP routes
(routes_coach.py) and subscribes to the event stream via /ws/coach.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import shlex
import time

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.domain import (
    AutonomyLevel,
    CoachAction,
    CoachLesson,
    CoachMessage,
    Flag,
    FlagSubmission,
    LlmUsage,
    Quest,
    QuestCheckpoint,
    Session,
    SessionState,
    TelemetryEvent,
    Track,
    UserProfile,
)
from .engine import get_engine
from .events import bus, publish_session

# patterns the coach may never execute (defense-in-depth; the kali is disposable
# but the *host* and other quest VMs must be out of reach)
DENIED_PATTERNS = [
    "rm -rf /", "mkfs", ":(){", "dd if=", "shutdown", "poweroff", "reboot",
    "iptables -F", "nft flush", ">/dev/sd", "wipefs",
]


def _is_denied(command: str) -> bool:
    low = command.lower()
    return any(p in low for p in DENIED_PATTERNS)


async def session_context(db: AsyncSession, session_id: int) -> dict:
    """Everything the coach needs for its reasoning loop."""
    session = await db.get(Session, session_id)
    if not session:
        return {}
    quest = await db.get(Quest, session.quest_id)
    track = await db.get(Track, quest.track_slug) if quest else None
    flags = (await db.execute(select(Flag).where(Flag.quest_id == session.quest_id))).scalars().all()
    solved = {
        r.flag_key for r in (await db.execute(
            select(FlagSubmission).where(
                FlagSubmission.session_id == session_id, FlagSubmission.correct.is_(True)))
        ).scalars().all()
    }
    checkpoints = {
        r.checkpoint_id for r in (await db.execute(
            select(QuestCheckpoint).where(QuestCheckpoint.session_id == session_id))).scalars().all()
    }
    # submit outcomes — replayed into FactsDB on coach attach so a restart
    # can't resurrect already-accepted (or already-rejected) flag values
    flag_submits = [
        {"value": r.value, "correct": bool(r.correct)}
        for r in (await db.execute(
            select(FlagSubmission.value, FlagSubmission.correct).where(
                FlagSubmission.session_id == session_id))).all()]
    # finished worker reports (meta.agent tagged) — a coach restart drops
    # the roster entirely; replaying the reports merges their findings back
    worker_reports = [
        {"agent": r[0], "content": r[1]}
        for r in (await db.execute(
            select(func.json_extract(CoachMessage.meta, "$.agent"),
                   CoachMessage.content).where(
                CoachMessage.session_id == session_id,
                CoachMessage.kind == "action_report",
                func.json_extract(CoachMessage.meta, "$.agent").is_not(None))
            .order_by(CoachMessage.id.desc()).limit(6))).all()
        if r[0]]
    # the agent's own roadmap (update_plan writes it, restarts must not
    # lose it) — full-replace semantics → the latest main-agent snapshot
    # IS the plan; worker plan rows are audit-only (workers die on restart)
    plan_raw = (await db.execute(
        select(func.json_extract(CoachAction.args, "$.items")).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "update_plan",
            func.coalesce(
                func.json_extract(CoachAction.args, "$.agent"), "main")
            == "main")
        .order_by(CoachAction.id.desc()).limit(1))).scalar()
    # json_extract yields a JSON string for arrays — back to a list
    try:
        plan = json.loads(plan_raw) if isinstance(plan_raw, str) else (plan_raw or [])
    except (TypeError, ValueError):
        plan = []
    if not isinstance(plan, list):
        plan = []
    # orphaned workers — spawned but never finished/killed. Their command
    # outputs reseed via coach_outputs, but the roster (and each worker's
    # task) dies with the coach process; without this note the parent
    # re-does their work or searches for their files on the wrong host
    # (s46: w1 wrote /tmp/backup-modified.sh on shop01, post-restart the
    # parent looked for it on Kali)
    spawn_rows = (await db.execute(
        select(func.json_extract(CoachAction.args, "$.worker_id"),
               func.json_extract(CoachAction.args, "$.task")).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "spawn_agent")
        .order_by(CoachAction.id.desc()).limit(8))).all()
    finished_or_killed = {w["agent"] for w in worker_reports}
    finished_or_killed |= {
        str(r[0]) for r in (await db.execute(
            select(func.json_extract(CoachAction.args, "$.worker_id")).where(
                CoachAction.session_id == session_id,
                CoachAction.tool == "kill_agent"))).all() if r[0]}
    worker_orphans = [
        {"agent": str(r[0]), "task": str(r[1])[:160]}
        for r in reversed(spawn_rows)
        if r[0] and str(r[0]) not in finished_or_killed]
    # private none-reason notes — the coach's working memory; last 10 in
    # chronological order for the reseed (cap 8 applies coach-side)
    coach_notes = [r[0] for r in (await db.execute(
        select(func.json_extract(CoachAction.args, "$.text")).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "note")
        .order_by(CoachAction.id.desc()).limit(10))).all() if r[0]]
    coach_notes.reverse()
    # agent-authored lessons (record_lesson tool) — the model's own
    # distilled session knowledge; replayed into FactsDB.lessons on attach
    # so hard-won facts survive a coach restart like any other fact type
    lessons = [{"text": r[0], "agent": r[1]}
               for r in (await db.execute(
                   select(func.json_extract(CoachAction.args, "$.text"),
                          func.coalesce(
                              func.json_extract(CoachAction.args, "$.agent"),
                              "main")).where(
                       CoachAction.session_id == session_id,
                       CoachAction.tool == "record_lesson")
                   .order_by(CoachAction.id.desc()).limit(10))).all()
               if r[0]]
    lessons.reverse()
    # coverage-ledger + shared-notes + findings writer log (record_coverage,
    # update_coverage, create_note, record_finding) — chronological replay
    # rebuilds the agent-owned bookkeeping after a coach restart, like
    # update_plan does for the roadmap. Desc→reverse keeps the LATEST 96.
    ledger_log = [
        {"tool": r[0], "args": r[1]} for r in reversed((await db.execute(
            select(CoachAction.tool, CoachAction.args).where(
                CoachAction.session_id == session_id,
                CoachAction.tool.in_(
                    ["record_coverage", "update_coverage", "create_note",
                     "record_finding"]))
            .order_by(CoachAction.id.desc()).limit(96))).all())]
    # observer field notes — session-scoped by applies (global + this
    # track + this quest); consumed via push-hints and lookup_guide only,
    # never rendered into the base prompt
    field_notes = [{"id": n.id, "text": n.text, "tags": n.tags or []}
                   for n in await active_lessons(
                       db, track=quest.track_slug if quest else None,
                       quest_id=session.quest_id)]
    telem = (await db.execute(
        select(TelemetryEvent).where(TelemetryEvent.session_id == session_id)
        .order_by(TelemetryEvent.id.desc()).limit(60))).scalars().all()
    msgs = (await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == session_id)
        .order_by(CoachMessage.id.desc()).limit(30))).scalars().all()
    # "error" counts: a failed command still executed on the box and burned
    # a turn — excluding it lets thrash loops dodge the action budget (s84:
    # ~18 error execs turned GRACE 23→1 across a coach restart). Only
    # "denied" stays out — those never reached the agent.
    action_count = (await db.execute(
        select(func.count(CoachAction.id)).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "exec_in_kali",
            CoachAction.status.in_(["ok", "confirmed", "error"])))).scalar() or 0
    # exact commands the coach ran — replayed telemetry marks these
    # `from_coach` again so they never count as trainee activity after a
    # coach restart (keeps idle detection and anti-loop guards honest)
    coach_cmds = [
        {"command": r[0], "exitcode": r[1]}
        for r in (await db.execute(
            select(func.json_extract(CoachAction.args, "$.command"),
                   func.json_extract(CoachAction.result, "$.exitcode")).where(
                CoachAction.session_id == session_id,
                CoachAction.tool == "exec_in_kali",
                CoachAction.status.in_(["ok", "confirmed", "error"]))
            .order_by(CoachAction.id.desc()).limit(60))).all() if r[0]]
    # every tool output that ever showed a flag — replayed into the coach's
    # seen-flag evidence so a restart doesn't lose it (unverified submits
    # get challenged; already-seen values must not)
    flag_outs = [
        r[0] for r in (await db.execute(
            select(func.json_extract(CoachAction.result, "$.out")).where(
                CoachAction.session_id == session_id,
                CoachAction.tool.in_(["exec_in_kali", "type_in_pane"]),
                func.json_extract(CoachAction.result, "$.out")
                    .like("%pentrAIn{%")))).all() if r[0]]
    # exec/type results with their output — the coach replays these into its
    # FactsDB on attach so parsed facts (hosts/ports/creds/files) survive a
    # restart; commands alone would rebuild only the bookkeeping half
    coach_outs = [
        {"command": (f"<type> {r[1]}" if r[1] else (r[0] or "")),
         "window": r[2], "out": (r[3] or ""), "exitcode": r[4]}
        for r in (await db.execute(
            select(func.json_extract(CoachAction.args, "$.command"),
                   func.json_extract(CoachAction.args, "$.text"),
                   func.json_extract(CoachAction.args, "$.window"),
                   func.json_extract(CoachAction.result, "$.out"),
                   func.json_extract(CoachAction.result, "$.exitcode")).where(
                CoachAction.session_id == session_id,
                CoachAction.tool.in_(["exec_in_kali", "type_in_pane"]),
                # errored outputs carry the dead-end evidence (command not
                # found → missing:, Permission denied → denied:) — without
                # them a restart loses the denial facts and re-probes them
                CoachAction.status.in_(["ok", "confirmed", "error"]))
            .order_by(CoachAction.id.desc()).limit(160))).all() if r[0] or r[1]]
    profile = await db.get(UserProfile, 1)
    # home-lab LAN assessment: scope comes from the lan.scope_cidr setting,
    # falling back to the /24 of the WAN lease stored on the session. Only
    # relevant when the quest declares topology.kali.wan.
    scope = None
    if ((quest.topology or {}).get("kali") or {}).get("wan"):
        from . import settings as settings_svc
        scope = (await settings_svc.get_setting(db, "lan.scope_cidr", "") or "").strip()
        if not scope and session.kali_wan_ip:
            scope = f"{session.kali_wan_ip}/24"
    # resolve concrete target IPs for the coach — hostnames alone invite the
    # model to invent RFC-5737 addresses. The range's /24 prefix comes from
    # the live kali IP; quest topology supplies each vm's last octet.
    targets: list[dict] = []
    try:
        engine = await get_engine(db)
        st = (await engine.provider.status(session.range_id)
              if session.range_id else None)
        kali_ip = next(
            (v.ip for v in (st.vms if st else [])
             if v.ip and (v.role == "kali" or "kali" in v.name.lower())), None)
    except Exception:
        kali_ip = None
    for v in (quest.topology or {}).get("vms") or []:
        name = v.get("name")
        if not name:
            continue
        octet = v.get("ip_last_octet")
        ip = f"{kali_ip.rsplit('.', 1)[0]}.{octet}" if kali_ip and octet else None
        targets.append({"name": name, "ip": ip})
    if scope and not targets:
        targets.append({"name": "lan-scope", "ip": scope})
    return {
        "session": {
            "id": session.id, "state": session.state,
            "autonomy_level": session.autonomy_level,
            "coach_enabled": session.coach_enabled,
            "subagents_enabled": bool(session.subagents_enabled),
            "kali_vmid": session.kali_vmid,
            "kali_internet": bool(session.kali_internet),
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ready_at": session.ready_at.isoformat() if session.ready_at else None,
            "deploy_tail": (session.deploy_log or "")[-600:],
        },
        "quest": {
            "id": quest.id, "title": quest.title, "tier": quest.tier,
            "track": quest.track_slug, "briefing": quest.briefing_md,
            "coach_context": quest.coach_context_md,
            "checkpoints": quest.coach_cfg.get("checkpoints", []) if quest.coach_cfg else [],
            "escalation": quest.coach_cfg.get("escalation", {}) if quest.coach_cfg else {},
            # real hostnames + resolved IPs the trainee can reach — keeps the
            # model from inventing RFC-5737 addresses
            "targets": targets,
            # home-lab mode: authorized LAN scope + mode marker for prompts
            "scope": scope,
            "mode": "lan-assessment" if scope else None,
            # reference cards — tool syntax + methodology the model otherwise
            # has to recall (and gets wrong: --ssl-mode on mariadb, interactive
            # smbclient instead of -c)
            "cheatsheet": quest.cheatsheet_md or "",
            "track_cheatsheet": (track.cheatsheet_md if track else ""),
        },
        "session_tools": session.kali_tools or "",
        # engagement ROE snapshot — normalized operator whitelist; when
        # locked, the coach denies every IP/host outside it (scope.py).
        # Engagement packs (topology.engagement) with NO scope set yield a
        # synthetic 'required' scope: locked with an EMPTY whitelist, so the
        # guard denies everything until the operator declares authorization —
        # an unset whitelist must never degrade into "no baseline, allow all"
        "scope": (json.loads(session.scope_json)
                  if session.scope_json else
                  ({"version": 1, "locked": True, "required": True,
                    "mode": "external-engagement",
                    "authorized_by": "(not set — operator must POST scope)",
                    "nets": [], "hosts": [], "ports": []}
                   if (quest.topology or {}).get("engagement") else None)),
        "flags": [{"key": f.key, "name": f.name, "points": f.points,
                   "kind": f.kind,
                   "solved": f.key in solved} for f in flags],
        "checkpoints_hit": sorted(checkpoints),
        "telemetry_tail": [{"kind": t.kind, "payload": t.payload,
                            "ts": t.ts.isoformat() if t.ts else None} for t in telem],
        "messages": [{"role": m.role, "kind": m.kind, "content": m.content,
                      "ts": m.created_at.isoformat() if m.created_at else None} for m in msgs],
        "exec_count": int(action_count),
        "coach_commands": coach_cmds,
        "coach_outputs": coach_outs,
        "flag_outs": flag_outs,
        "flag_submits": flag_submits,
        "worker_reports": worker_reports,
        "worker_orphans": worker_orphans,
        "plan": plan,
        "coach_notes": coach_notes,
        "lessons": lessons,
        "ledger_log": ledger_log,
        "field_notes": field_notes,
        "profile": {"track_levels": profile.track_levels if profile else {},
                    "metrics": profile.metrics if profile else {}},
    }


_SECRET_PATTERNS = [
    re.compile(r"pentrAIn\{[^}]*\}"),
    re.compile(r"(?:-p|password|passwd|secret|token|apikey|api_key)\s*"
               r"[=: ]\s*['\"]?\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
]


def sanitize_lesson_text(text: str) -> str:
    """Strip flags/credentials from observer output before it becomes
    knowledge — a lesson must teach the move, never carry the loot."""
    t = str(text or "")
    for p in _SECRET_PATTERNS:
        t = p.sub("<redacted>", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:240]


def _jaccard(a: str, b: str) -> float:
    """Token-set similarity for lesson dedupe — order-independent,
    catches the 'same tip, different wording' case."""
    ta = {w for w in re.findall(r"[a-z0-9_./-]+", a.lower()) if len(w) > 2}
    tb = {w for w in re.findall(r"[a-z0-9_./-]+", b.lower()) if len(w) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


async def record_lesson(db: AsyncSession, session_id: int | None,
                        text: str, tags: list, applies: str = "global",
                        confidence: float = 0.5,
                        evidence: dict | None = None) -> CoachLesson | None:
    """Observer-written field note. Sanitized (no flags/creds), deduped
    against active lessons (Jaccard ≥0.7 → hit on the existing row),
    bounded. Returns the stored/merged row or None when rejected."""
    clean = sanitize_lesson_text(text)
    if len(clean) < 10 or clean.lower() == "<redacted>":
        return None
    existing = (await db.execute(
        select(CoachLesson).where(CoachLesson.status == "active")
        .order_by(CoachLesson.id.desc()).limit(60))).scalars().all()
    for row in existing:
        if _jaccard(row.text, clean) >= 0.7:
            row.hits = (row.hits or 0) + 1  # same lesson re-derived → stronger
            await db.commit()
            return row
    row = CoachLesson(
        session_id=session_id, text=clean,
        tags=[str(t)[:32].lower() for t in (tags or [])][:8],
        applies=applies, confidence=min(1.0, max(0.0, confidence or 0.5)),
        evidence=evidence or {}, source="observer")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def lesson_hit(db: AsyncSession, lesson_id: int) -> None:
    """Positive-attribution ping — a pushed field note was followed by
    progress. Rough but honest: it just counts later successes."""
    row = await db.get(CoachLesson, lesson_id)
    if row:
        row.hits = (row.hits or 0) + 1
        await db.commit()


async def post_observer_hint(db: AsyncSession, session_id: int,
                             text: str) -> None:
    """Live advisory from the observer into a running coach: persists a
    hint message (UI transparency + replay) and publishes a session event
    the coach picks up for guaranteed-read delivery on the next result."""
    clean = sanitize_lesson_text(text)[:400]
    if len(clean) < 10:
        return
    await post_message(db, session_id, "system", "hint", clean,
                       {"source": "observer"})
    await publish_session(session_id, "observer_hint", {"text": clean})


async def active_lessons(db: AsyncSession, *, track: str | None = None,
                         quest_id: int | None = None,
                         limit: int = 24) -> list[CoachLesson]:
    """Field notes a session may consume: global + its track + its quest,
    newest first. Disabled rows never surface."""
    scopes = ["global"]
    if track:
        scopes.append(f"track:{track}")
    if quest_id is not None:
        scopes.append(f"quest:{quest_id}")
    return (await db.execute(
        select(CoachLesson).where(
            CoachLesson.status == "active",
            CoachLesson.applies.in_(scopes))
        .order_by(CoachLesson.id.desc()).limit(limit))).scalars().all()


async def post_message(db: AsyncSession, session_id: int, role: str, kind: str,
                       content: str, meta: dict | None = None) -> CoachMessage:
    msg = CoachMessage(session_id=session_id, role=role, kind=kind,
                       content=content, meta=meta or {})
    db.add(msg)
    await db.commit()
    await bus.publish(f"coach.{session_id}", {
        "type": "coach_message", "session_id": session_id,
        "data": {"id": msg.id, "role": role, "kind": kind, "content": content, "meta": meta or {}}})
    return msg


async def record_action(db: AsyncSession, session_id: int, tool: str, args: dict,
                        result: dict, status: str = "ok") -> CoachAction:
    action = CoachAction(session_id=session_id, tool=tool, args=args,
                         result=result, status=status)
    db.add(action)
    await db.commit()
    await bus.publish(f"coach.{session_id}", {
        "type": "coach_action", "session_id": session_id,
        "data": {"id": action.id, "tool": tool, "status": status, "args": args}})
    return action


async def suggest_command(db: AsyncSession, session_id: int, command: str, why: str) -> CoachAction:
    """L3 copilot suggestion → pending action rendered as a run-on-kali chip."""
    if _is_denied(command):
        return await record_action(db, session_id, "suggest_command",
                                   {"command": command, "why": why},
                                   {"denied": True}, status="denied")
    action = await record_action(db, session_id, "suggest_command",
                                 {"command": command, "why": why}, {}, status="pending")
    await post_message(db, session_id, "coach", "suggestion", why,
                       {"command": command, "action_id": action.id})
    return action


async def exec_in_kali(db: AsyncSession, session_id: int, command: str,
                       window: str | None = None) -> dict:
    """Execute a command on the session's Kali via qemu-guest-agent.

    TAKEOVER (L4) only — copilot-level flows go through suggest_command +
    user confirmation (sessions.suggest_command_confirm runs them itself).
    Commands are also visible to the user — coach shells run in the
    'pentrain-coach' tmux session on the Kali desktop. `window` targets a
    named worker window (w1..w3) for parallel subagents.
    """
    session = await db.get(Session, session_id)
    if not session:
        return {"error": "session not found", "status": "error"}
    if session.state not in (SessionState.READY.value, SessionState.ACTIVE.value):
        return {"error": f"session state {session.state}", "status": "denied"}
    level = session.autonomy_level
    if level < AutonomyLevel.TAKEOVER.value:
        await record_action(db, session_id, "exec_in_kali", {"command": command},
                            {"reason": "autonomy too low"}, status="denied")
        return {"error": "autonomy level too low — use suggest_command", "status": "denied"}
    if _is_denied(command):
        await record_action(db, session_id, "exec_in_kali", {"command": command},
                            {"reason": "denied pattern"}, status="denied")
        return {"error": "command denied by guardrails", "status": "denied"}
    if not session.kali_vmid:
        return {"error": "no kali vmid", "status": "error"}

    engine = await get_engine(db)
    try:
        res = await exec_visible_in_kali(engine, session.kali_vmid, command,
                                         session_id=session_id, window=window)
        status = "ok" if res.get("exitcode", 0) == 0 else "error"
        args = {"command": command}
        if window:
            args["window"] = window
        await record_action(db, session_id, "exec_in_kali", args, res,
                            status=status)
        return {**res, "status": status}
    except Exception as e:
        await record_action(db, session_id, "exec_in_kali",
                            {"command": command}, {"error": str(e)}, status="error")
        return {"error": str(e), "status": "error"}


async def type_in_pane(db: AsyncSession, session_id: int, text: str,
                       window: str | None = None) -> dict:
    """Type a line of INPUT into the busy coach pane — TAKEOVER only.

    Interactive flows can't go through exec_in_kali: a foreground program
    (ssh/ftp/nc/su/sudo password prompts, menus, remote shells) holds the
    pane and the busy-check bounces everything. This types the literal
    line + Enter and returns the pane tail so the model sees the effect.
    Exit codes inside interactive sessions aren't available — the model
    can type `echo $?` itself when it needs one.
    """
    session = await db.get(Session, session_id)
    if not session:
        return {"error": "session not found", "status": "error"}
    if session.state not in (SessionState.READY.value, SessionState.ACTIVE.value):
        return {"error": f"session state {session.state}", "status": "denied"}
    if session.autonomy_level < AutonomyLevel.TAKEOVER.value:
        await record_action(db, session_id, "type_in_pane", {"text": text[:80]},
                            {"reason": "autonomy too low"}, status="denied")
        return {"error": "autonomy level too low", "status": "denied"}
    if not session.kali_vmid:
        return {"error": "no kali vmid", "status": "error"}
    engine = await get_engine(db)
    try:
        # remember where the cursor sits BEFORE typing — the typed line
        # echoes at history_size + cursor_y, and the input's EFFECT is
        # everything after it. Returning only that slice matters: a raw
        # 50-line tail shows stale scrollback ("No such file" from an old
        # attempt looks identical to a fresh failure). One guest call does
        # the probe + both key sends (they queue in order; `send-keys -l`
        # keeps passwords/special chars literal, Enter stays a real key).
        target = _pane_target(window)
        pre = await engine.pve.agent_exec_sh(
            session.kali_vmid,
            f"{_tmux_ensure_sh(window)}"
            f"tmux display-message -p -t {target} "
            "'#{history_size} #{cursor_y}'; "
            f"tmux send-keys -t {target} -l {shlex.quote(text)}; "
            f"tmux send-keys -t {target} Enter", timeout_s=10)
        try:
            h0, cy0 = (int(x) for x in (pre.get("out") or "").split()[:2])
        except (ValueError, IndexError):
            h0, cy0 = -1, 0
        # give the foreground program a beat to react, then capture + read
        # the resulting foreground command in ONE guest call
        await asyncio.sleep(0.6)
        nonce = secrets.token_hex(5)
        pane = await engine.pve.agent_exec_sh(
            session.kali_vmid,
            f"tmux capture-pane -pJ -t {target} -S - 2>/dev/null; "
            f"echo @@FG:{nonce}@@; "
            f"tmux display-message -p -t {target} "
            "'#{pane_current_command}'", timeout_s=10)
        p_out = pane.get("out") or ""
        body, _, cur_part = p_out.rpartition(f"@@FG:{nonce}@@")
        lines = body.rstrip("\n").splitlines()
        cur = cur_part.strip()
        if h0 >= 0 and h0 + cy0 < len(lines):
            # echo of our input + everything it produced + the new prompt
            out = "\n".join(lines[h0 + cy0:])[-3000:]
        else:
            out = "\n".join(lines[-50:])[-3000:]
        # is the pane STILL held by a foreground program (ssh session, vim,
        # ftp) or did our input return it to the shell? The coach's
        # interactive fast-path keys off this: still-busy means the next
        # input should follow at LLM cadence, not the ~90s reflect tick.
        busy = bool(cur) and cur not in ("zsh", "bash", "sh", "fish", "tmux")
        await record_action(db, session_id, "type_in_pane", {"text": text[:80]},
                            {"out": out[-600:]}, status="ok")
        if session_id:
            await publish_session(session_id, "coach_activity", {
                "active": True, "agent": window or "main",
                "text": f"{f'[{window}] ' if window else ''}"
                        "typing input in the pane",
                "output": out[-1500:]}, sticky=True)
        return {"out": out, "visible": True, "exitcode": None,
                "current_command": cur, "busy": busy}
    except Exception as e:
        await record_action(db, session_id, "type_in_pane", {"text": text[:80]},
                            {"error": str(e)}, status="error")
        return {"error": str(e), "status": "error"}


async def submit_flag(db: AsyncSession, session_id: int, value: str) -> dict:
    """Coach submits a flag value — TAKEOVER only. Same scoring path as the
    user endpoint (wrong values count as submissions)."""
    session = await db.get(Session, session_id)
    if not session:
        return {"error": "session not found", "status": "error"}
    if session.autonomy_level < AutonomyLevel.TAKEOVER.value:
        await record_action(db, session_id, "submit_flag", {"value": value[:80]},
                            {"reason": "autonomy too low"}, status="denied")
        return {"error": "autonomy level too low", "status": "denied"}
    from . import sessions as sessions_svc  # lazy — sessions imports this module
    try:
        res = await sessions_svc.submit_flag(db, session_id, value)
    except sessions_svc.SessionError as e:
        return {"error": str(e), "status": "error"}
    await record_action(db, session_id, "submit_flag", {"value": value[:80]}, res,
                        status="ok" if res.get("correct") else "error")
    return {**res, "status": "ok" if res.get("correct") else "error"}


async def check_flag(db: AsyncSession, session_id: int, flag_key: str) -> dict:
    """Coach triggers a server-side command-flag check — TAKEOVER only."""
    session = await db.get(Session, session_id)
    if not session:
        return {"error": "session not found", "status": "error"}
    if session.autonomy_level < AutonomyLevel.TAKEOVER.value:
        await record_action(db, session_id, "check_flag", {"flag_key": flag_key},
                            {"reason": "autonomy too low"}, status="denied")
        return {"error": "autonomy level too low", "status": "denied"}
    from . import sessions as sessions_svc
    try:
        res = await sessions_svc.check_flag(db, session_id, flag_key)
    except sessions_svc.SessionError as e:
        return {"error": str(e), "status": "error"}
    await record_action(db, session_id, "check_flag", {"flag_key": flag_key}, res,
                        status="ok" if res.get("correct") else "error")
    return {**res, "status": "ok" if res.get("correct") else "error"}


COACH_TMUX = "pentrain-coach"


def _pane_target(window: str | None) -> str:
    """tmux target for a pane — main session window by default, a named
    worker window (pentrain-coach:w1..w3) for parallel subagents."""
    return f"{COACH_TMUX}:{window}" if window else COACH_TMUX


def _tmux_ensure_sh(window: str | None) -> str:
    """Shell fragment ensuring the worker window exists — new-window is NOT
    idempotent (duplicate names allowed), so list-windows|grep guards it.
    -d keeps the desktop focus on the current window."""
    if not window:
        return ""
    q = shlex.quote(window)
    return (f"tmux has-session -t {COACH_TMUX} 2>/dev/null "
            f"|| tmux new-session -d -s {COACH_TMUX}; "
            f"tmux list-windows -t {COACH_TMUX} -F '#{{window_name}}' "
            f"| grep -qx {q} "
            f"|| tmux new-window -d -t {COACH_TMUX} -n {q}; ")


async def exec_visible_in_kali(engine, kali_vmid: int, command: str,
                               timeout_s: int = 60,
                               session_id: int | None = None,
                               window: str | None = None) -> dict:
    """Run a command INSIDE the 'pentrain-coach' tmux on the Kali desktop so the
    trainee literally watches the coach type. Falls back to a detached guest-agent
    shell when no desktop/tmux exists (agent provisioning still pending, mock, etc).

    Output is recovered via a unique end-marker + capture-pane, so the result has
    the real stdout/stderr text and exit code instead of scrollback noise.
    With session_id set, each poll also relays the live output tail as a
    coach_activity event — the chat shows the command's progress in real time.
    """
    marker = f"PTN{secrets.token_hex(5)}"
    shells = ("bash", "zsh", "sh", "dash", "ksh", "fish")
    target = _pane_target(window)
    # ONE guest call for all probes — session check, worker-window ensure,
    # foreground command and last pane line ride in a single QGA round-trip
    # (was 3 sequential calls ≈ +2 HTTP+agent latencies per exec)
    probe = await engine.pve.agent_exec_sh(
        kali_vmid,
        f"if tmux has-session -t {COACH_TMUX} 2>/dev/null; then "
        f"{_tmux_ensure_sh(window)}"
        f"echo @@OK:{marker}@@; "
        f"tmux display-message -p -t {target} '#{{pane_current_command}}'; "
        f"echo @@SEP:{marker}@@; "
        f"tmux capture-pane -pt {target} 2>/dev/null | grep -v '^$' "
        "| tail -1; "
        f"else echo @@NOSESSION:{marker}@@; fi", timeout_s=10)
    p_out = probe.get("out") or ""
    if f"@@OK:{marker}@@" not in p_out:
        # no desktop session (autologin pending / headless boot / headless
        # provider) — create the channel detached; a later xfce login
        # attaches to the same session
        await engine.pve.agent_exec_sh(
            kali_vmid, f"tmux new-session -d -s {COACH_TMUX}; "
            f"{_tmux_ensure_sh(window)}", timeout_s=10)
        probe = await engine.pve.agent_exec_sh(
            kali_vmid, f"tmux has-session -t {COACH_TMUX}", timeout_s=10)
        if probe.get("exitcode", 1) != 0:
            return await engine.pve.agent_exec_sh(kali_vmid, command, timeout_s=timeout_s)
        fg_cmd, last = "", ""   # fresh detached session — shell at prompt
    else:
        parts = p_out.split(f"@@SEP:{marker}@@")
        fg_cmd = parts[0].split(f"@@OK:{marker}@@")[-1].strip()
        last = parts[-1].strip() if len(parts) > 1 else ""

    # ctrl-key passthrough — "C-c"/"C-d"/"C-z" must reach the pane as real
    # keys, not typed text, so a wedged foreground process can be freed.
    # Report the resulting foreground command so the caller can SEE the
    # interrupt worked instead of blindly re-sending C-c.
    if re.fullmatch(r"C-[a-z]", command.strip()):
        await engine.pve.agent_exec_sh(
            kali_vmid,
            f"tmux send-keys -t {target} {command.strip()}", timeout_s=10)
        await asyncio.sleep(0.4)
        fg = await engine.pve.agent_exec_sh(
            kali_vmid,
            f"tmux display-message -p -t {target} "
            "'#{pane_current_command}'", timeout_s=10)
        now = (fg.get("out") or "").strip()
        state = (f"pane free — shell '{now}' at prompt" if now in shells
                 else f"still busy — foreground: '{now}'")
        return {"out": f"(sent {command.strip()} — {state})", "err": "",
                "exitcode": 0, "visible": True}

    # pane busy? typed lines would buffer into the foreground process's stdin
    # and never reach the shell — tell the caller to free the pane first.
    # Two checks: (a) a non-shell foreground command, (b) a continuation
    # prompt (heredoc/quote) — pane_current_command stays 'zsh' while the
    # shell waits for a delimiter, so typed lines land as heredoc input.
    if fg_cmd and fg_cmd not in shells:
        return {"out": "", "visible": True, "busy": True, "exitcode": None,
                "err": (f"pane busy: '{fg_cmd}' is running interactively — "
                        "use type_in_pane to send input lines into it (e.g. "
                        "passwords, menu choices), or send 'C-c' via "
                        "exec_in_kali to interrupt it")}
    if re.search(r"(heredoc|dquote|quote|pipe)?>\s*$", last) and last != ">":
        return {"out": "", "visible": True, "busy": True, "exitcode": None,
                "err": (f"pane busy: shell awaits more input ({last[-40:]!r} "
                        "— unfinished heredoc/quote?) — use type_in_pane to "
                        "send the missing line/delimiter, or 'C-c' via "
                        "exec_in_kali to reset the prompt")}

    # two SEPARATE key sends in ONE guest call — appending `; echo …` to the
    # command line broke heredocs (a `EOF ; echo` line isn't a valid
    # delimiter) and swallowed the output slice; separate send-keys queue in
    # order, so heredocs stay intact. The B end-marker is sent only AFTER the
    # pane returns to a shell: typed while the command still runs, it buffers
    # into the process's stdin — programs that read keystrokes (nmap
    # interactive keys, less, top, ssh, vi) EAT the marker line and
    # completion is never detected.
    if "\n" in command or len(command) > 180:
        # multiline/long commands go via guest-file-write + `bash file` —
        # embedding them in the send-keys guest-exec ARG is exactly what
        # wedges the virtio channel on this host (see agent_file_write's
        # docstring; two live qga deaths at heredoc-time in s49/s50)
        script = f"/tmp/ptn-{marker}.sh"
        await engine.pve.agent_file_write(
            kali_vmid, script, command + "\n")
        typed_line = f"bash {script}"
    else:
        typed_line = command
    n_cmd_lines = typed_line.count("\n") + 1
    await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux send-keys -t {target} {shlex.quote(f'echo {marker}A')} Enter; "
        f"tmux send-keys -t {target} {shlex.quote(typed_line)} Enter",
        timeout_s=10)

    # -J joins wrapped lines so each typed line maps to exactly one pane line;
    # flag order matters — `-ptJ` parses as `-t J` and the capture fails
    pane_cmd = (f"tmux capture-pane -pJ -t {target} -S -1500 2>/dev/null "
                "| tail -800")
    fg_probe = (f"tmux display-message -p -t {target} "
                "'#{pane_current_command}'")
    # only real marker *output* lines count: `PTN…A` alone, `PTN…B:<digits>`
    begin = re.compile(rf"{re.escape(marker)}A\s*$")
    end = re.compile(rf"{re.escape(marker)}B:(\d+)\s*$")
    cont_re = re.compile(r"(heredoc|dquote|quote|pipe)?>\s*$")
    cmd_tail = typed_line.split("\n")[-1][-60:].rstrip()
    deadline = time.monotonic() + timeout_s
    last_tail = ""
    b_sent = False
    while time.monotonic() < deadline:
        pane = await engine.pve.agent_exec_sh(kali_vmid, pane_cmd, timeout_s=15)
        lines = (pane.get("out") or "").splitlines()
        ai = bi = -1
        exitcode = 0
        for i in range(len(lines) - 1, -1, -1):
            if bi < 0 and (m := end.search(lines[i])):
                bi, exitcode = i, int(m.group(1))
            if ai < 0 and begin.search(lines[i]):
                ai = i
            if ai >= 0 and bi >= 0:
                break
        if ai >= 0 and bi >= 0:
            # typed command lines sit between PTNA and the output — their
            # exact pane-line count is unreliable (multi-line zsh prompt,
            # heredoc `>` prefixes). Anchor on the typed text itself: the
            # last typed line ends with the command's own tail.
            typed_end = next(
                (i for i in range(bi - 2, ai, -1)
                 if cmd_tail and lines[i].rstrip().endswith(cmd_tail)),
                ai + n_cmd_lines)
            # last line before the typed `echo PTN…B` is the first half of
            # the next two-line zsh prompt (`(host)-[cwd]`) — drop it
            out_lines = [ln for ln in lines[typed_end + 1:bi - 1]
                         if ln.strip() and marker not in ln]
            if out_lines and re.search(r"\)-\[[^\]]*\]\s*$", out_lines[-1]):
                out_lines.pop()
            out = "\n".join(out_lines)[-4000:]
            return {"out": out, "err": "", "exitcode": exitcode, "visible": True}
        if ai >= 0:
            # live output-so-far: everything after the typed command lines,
            # marker text hidden so the sentinels never reach the chat
            typed_end = next(
                (i for i in range(len(lines) - 1, ai, -1)
                 if cmd_tail and lines[i].rstrip().endswith(cmd_tail)),
                ai + n_cmd_lines)
            tail = "\n".join(ln for ln in lines[typed_end + 1:]
                             if ln.strip() and marker not in ln)[-3000:]
            if session_id and tail != last_tail:
                last_tail = tail
                await publish_session(session_id, "coach_activity", {
                    "active": True, "agent": window or "main",
                    "text": f"{f'[{window}] ' if window else ''}"
                            f"executing `{command[:90]}`",
                    "output": tail}, sticky=True)
            if not b_sent:
                # completion = pane back at a shell, the typed command line
                # already visible (send raced ahead of the echo), and no
                # continuation prompt (heredoc/quote — zsh looks 'free' then)
                fg = await engine.pve.agent_exec_sh(
                    kali_vmid, fg_probe, timeout_s=10)
                fg_cmd = (fg.get("out") or "").strip()
                typed_seen = (not cmd_tail) or any(
                    ln.rstrip().endswith(cmd_tail) for ln in lines[ai:])
                last_ln = next(
                    (ln.strip() for ln in reversed(lines) if ln.strip()), "")
                if (fg_cmd in shells and typed_seen and last_ln != ">"
                        and not cont_re.search(last_ln)):
                    await engine.pve.agent_exec_sh(
                        kali_vmid,
                        f"tmux send-keys -t {target} "
                        f"{shlex.quote(f'echo {marker}B:$?')} Enter",
                        timeout_s=10)
                    b_sent = True
        await asyncio.sleep(0.35)
    # timed out but still typed — the partial pane tail beats a dead end
    return {"out": last_tail
            or "(still running — visible in the pentrain-coach tmux window)",
            "err": ("still running — pane is now busy; further commands "
                    "bounce until it finishes or you send 'C-c'. If it is "
                    "waiting for INPUT (password/menu prompt), answer NOW "
                    "with type_in_pane — prompts time out"),
            "exitcode": None, "visible": True, "timed_out": True}


async def capture_screen(db: AsyncSession, session_id: int) -> dict:
    """Screenshot the Kali desktop → base64 PNG (for vision-capable coach models)."""
    session = await db.get(Session, session_id)
    if not session or not session.kali_vmid:
        return {"error": "no kali"}
    engine = await get_engine(db)
    try:
        await engine.pve.agent_exec_sh(
            session.kali_vmid,
            "import -window root /tmp/pentrain-screen.png 2>/dev/null "
            "|| scrot -o /tmp/pentrain-screen.png 2>/dev/null || true")
        data = await engine.pve.agent_file_read(session.kali_vmid, "/tmp/pentrain-screen.png")
        return {"png_b64": base64.b64encode(data).decode(), "bytes": len(data)}
    except Exception as e:
        return {"error": str(e)}


async def mark_checkpoint(db: AsyncSession, session_id: int, checkpoint_id: str) -> None:
    try:
        db.add(QuestCheckpoint(session_id=session_id, checkpoint_id=checkpoint_id))
        await db.commit()
    except IntegrityError:  # concurrent detectors — first writer wins
        await db.rollback()
        return
    await bus.publish(f"session.{session_id}", {
        "type": "checkpoint", "session_id": session_id, "data": {"checkpoint": checkpoint_id}})


async def agent_metrics(db: AsyncSession, session_id: int) -> dict | None:
    """Aggregate per-session agent behavior for GET /sessions/{id}/agent-metrics.

    Sources: coach_actions (tool calls incl. self-reported guard denials),
    flag_submissions (grounding + time-to-flag), llm_usage (tokens). These
    are the eval metrics from the agent-research roadmap — tool-call
    accuracy, denial/hallucination signals, recovery, steps-to-success —
    computed from the audit trail, not inferred from chat logs.
    """
    s = await db.get(Session, session_id)
    if not s:
        return None
    actions = (await db.execute(
        select(CoachAction).where(CoachAction.session_id == session_id)
        .order_by(CoachAction.id))).scalars().all()
    subs = (await db.execute(
        select(FlagSubmission).where(FlagSubmission.session_id == session_id)
        .order_by(FlagSubmission.id))).scalars().all()
    usage = (await db.execute(
        select(LlmUsage).where(LlmUsage.session_id == session_id)
        )).scalars().all()

    tool_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    deny_reasons: dict[str, int] = {}
    exec_ok = exec_err = 0
    for a in actions:
        tool_counts[a.tool] = tool_counts.get(a.tool, 0) + 1
        status_counts[a.status] = status_counts.get(a.status, 0) + 1
        if a.status == "denied":
            reason = str((a.result or {}).get("reason")
                         or (a.result or {}).get("error")
                         or ("guardrail" if (a.result or {}).get("denied")
                             else "?"))[:120]
            deny_reasons[reason] = deny_reasons.get(reason, 0) + 1
        if a.tool == "exec_in_kali":
            if a.status == "ok":
                exec_ok += 1
            elif a.status == "error":
                exec_err += 1

    accepted = [x for x in subs if x.correct]
    rejected = [x for x in subs if not x.correct]
    # grounding signals: a submit of a value never observed in tool output
    # (self-reported by the coach as denied 'never observed in output'),
    # foreign-ip denials, and rejected submissions
    unverified_submits = sum(
        1 for a in actions
        if a.tool == "submit_flag" and a.status == "denied")
    foreign_ip_denials = sum(
        n for r, n in deny_reasons.items() if "known target" in r)
    t0 = s.ready_at or s.created_at
    t_first = accepted[0].submitted_at if accepted else None
    time_to_flag = (
        round((t_first - t0).total_seconds(), 1)
        if t_first and t0 else None)
    span = (
        round((actions[-1].created_at - actions[0].created_at)
              .total_seconds(), 1)
        if len(actions) > 1 and actions[0].created_at else 0.0)
    return {
        "session_id": session_id,
        "actions_total": len(actions),
        "tool_counts": dict(sorted(tool_counts.items(),
                                   key=lambda kv: -kv[1])),
        "status_counts": status_counts,
        "denied": {
            "total": status_counts.get("denied", 0),
            "reasons": dict(sorted(deny_reasons.items(),
                                   key=lambda kv: -kv[1])[:12]),
        },
        "exec": {"ok": exec_ok, "error": exec_err},
        "hallucination": {
            "foreign_ip_denials": foreign_ip_denials,
            "unverified_flag_submits": unverified_submits,
            "rejected_flag_submits": len(rejected),
        },
        "flags": {
            "submitted": len(subs),
            "accepted": len(accepted),
            "first_flag_key": accepted[0].flag_key if accepted else None,
            "time_to_first_flag_s": time_to_flag,
        },
        "llm": {
            "calls": len(usage),
            "total_tokens": sum(x.total_tokens for x in usage),
            "prompt_tokens": sum(x.prompt_tokens for x in usage),
            "completion_tokens": sum(x.completion_tokens for x in usage),
        },
        "span_s": span,
    }
