"""Coach bridge: internal API surface consumed by the coach service.

The coach is a separate container; it calls these functions via HTTP routes
(routes_coach.py) and subscribes to the event stream via /ws/coach.
"""
from __future__ import annotations

import asyncio
import base64
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
    CoachMessage,
    Flag,
    FlagSubmission,
    Quest,
    QuestCheckpoint,
    Session,
    SessionState,
    TelemetryEvent,
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
    telem = (await db.execute(
        select(TelemetryEvent).where(TelemetryEvent.session_id == session_id)
        .order_by(TelemetryEvent.id.desc()).limit(60))).scalars().all()
    msgs = (await db.execute(
        select(CoachMessage).where(CoachMessage.session_id == session_id)
        .order_by(CoachMessage.id.desc()).limit(30))).scalars().all()
    action_count = (await db.execute(
        select(func.count(CoachAction.id)).where(
            CoachAction.session_id == session_id,
            CoachAction.tool == "exec_in_kali",
            CoachAction.status.in_(["ok", "confirmed"])))).scalar() or 0
    profile = await db.get(UserProfile, 1)
    return {
        "session": {
            "id": session.id, "state": session.state,
            "autonomy_level": session.autonomy_level,
            "coach_enabled": session.coach_enabled,
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
            # real hostnames the trainee can reach — resolve on kali via
            # range DNS; keeps the model from inventing RFC-5737 IPs
            "targets": [v.get("name") for v in
                        ((quest.topology or {}).get("vms") or [])
                        if v.get("name")],
        },
        "flags": [{"key": f.key, "name": f.name, "points": f.points,
                   "solved": f.key in solved} for f in flags],
        "checkpoints_hit": sorted(checkpoints),
        "telemetry_tail": [{"kind": t.kind, "payload": t.payload,
                            "ts": t.ts.isoformat() if t.ts else None} for t in telem],
        "messages": [{"role": m.role, "kind": m.kind, "content": m.content,
                      "ts": m.created_at.isoformat() if m.created_at else None} for m in msgs],
        "exec_count": int(action_count),
        "profile": {"track_levels": profile.track_levels if profile else {},
                    "metrics": profile.metrics if profile else {}},
    }


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


async def exec_in_kali(db: AsyncSession, session_id: int, command: str) -> dict:
    """Execute a command on the session's Kali via qemu-guest-agent.

    TAKEOVER (L4) only — copilot-level flows go through suggest_command +
    user confirmation (sessions.suggest_command_confirm runs them itself).
    Commands are also visible to the user — coach shells run in the
    'pentrain-coach' tmux session on the Kali desktop.
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
                                         session_id=session_id)
        status = "ok" if res.get("exitcode", 0) == 0 else "error"
        await record_action(db, session_id, "exec_in_kali",
                            {"command": command}, res, status=status)
        return {**res, "status": status}
    except Exception as e:
        await record_action(db, session_id, "exec_in_kali",
                            {"command": command}, {"error": str(e)}, status="error")
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


async def exec_visible_in_kali(engine, kali_vmid: int, command: str,
                               timeout_s: int = 60,
                               session_id: int | None = None) -> dict:
    """Run a command INSIDE the 'pentrain-coach' tmux on the Kali desktop so the
    trainee literally watches the coach type. Falls back to a detached guest-agent
    shell when no desktop/tmux exists (agent provisioning still pending, mock, etc).

    Output is recovered via a unique end-marker + capture-pane, so the result has
    the real stdout/stderr text and exit code instead of scrollback noise.
    With session_id set, each poll also relays the live output tail as a
    coach_activity event — the chat shows the command's progress in real time.
    """
    probe = await engine.pve.agent_exec_sh(
        kali_vmid, f"tmux has-session -t {COACH_TMUX}", timeout_s=10)
    if probe.get("exitcode", 1) != 0:
        # no desktop session (autologin pending / headless boot) — create the
        # channel detached; a later xfce login attaches to the same session
        await engine.pve.agent_exec_sh(
            kali_vmid, f"tmux new-session -d -s {COACH_TMUX}", timeout_s=10)
        probe = await engine.pve.agent_exec_sh(
            kali_vmid, f"tmux has-session -t {COACH_TMUX}", timeout_s=10)
    if probe.get("exitcode", 1) != 0:
        return await engine.pve.agent_exec_sh(kali_vmid, command, timeout_s=timeout_s)

    # ctrl-key passthrough — "C-c"/"C-d"/"C-z" must reach the pane as real
    # keys, not typed text, so a wedged foreground process can be freed.
    # Report the resulting foreground command so the caller can SEE the
    # interrupt worked instead of blindly re-sending C-c.
    if re.fullmatch(r"C-[a-z]", command.strip()):
        await engine.pve.agent_exec_sh(
            kali_vmid,
            f"tmux send-keys -t {COACH_TMUX} {command.strip()}", timeout_s=10)
        await asyncio.sleep(0.7)
        fg = await engine.pve.agent_exec_sh(
            kali_vmid,
            f"tmux display-message -p -t {COACH_TMUX} "
            "'#{pane_current_command}'", timeout_s=10)
        now = (fg.get("out") or "").strip()
        state = (f"pane free — shell '{now}' at prompt" if now in
                 ("bash", "zsh", "sh", "dash", "ksh", "fish")
                 else f"still busy — foreground: '{now}'")
        return {"out": f"(sent {command.strip()} — {state})", "err": "",
                "exitcode": 0, "visible": True}

    # pane busy? typed lines would buffer into the foreground process's stdin
    # and never reach the shell — tell the caller to free the pane first.
    # Two checks: (a) a non-shell foreground command, (b) a continuation
    # prompt (heredoc/quote) — pane_current_command stays 'zsh' while the
    # shell waits for a delimiter, so typed lines land as heredoc input.
    fg = await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux display-message -p -t {COACH_TMUX} '#{{pane_current_command}}'",
        timeout_s=10)
    fg_cmd = (fg.get("out") or "").strip()
    if fg_cmd and fg_cmd not in ("bash", "zsh", "sh", "dash", "ksh", "fish"):
        return {"out": "", "visible": True, "busy": True, "exitcode": None,
                "err": (f"pane busy: '{fg_cmd}' is still running — send "
                        "'C-c' via exec_in_kali to interrupt it, or wait "
                        "for it to finish")}
    tail = await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux capture-pane -pt {COACH_TMUX} 2>/dev/null | grep -v '^$' "
        "| tail -1", timeout_s=10)
    last = (tail.get("out") or "").strip()
    if re.search(r"(heredoc|dquote|quote|pipe)?>\s*$", last) and last != ">":
        return {"out": "", "visible": True, "busy": True, "exitcode": None,
                "err": (f"pane busy: shell awaits more input ({last[-40:]!r} "
                        "— unfinished heredoc/quote?) — send 'C-c' via "
                        "exec_in_kali to reset the prompt")}

    marker = f"PTN{secrets.token_hex(5)}"
    # three SEPARATE key sends — appending `; echo …` to the command line broke
    # heredocs (a `EOF ; echo` line isn't a valid delimiter) and swallowed the
    # output slice. Start-marker, raw command, end-marker keeps every typed
    # line intact and brackets the real output between two unique sentinels.
    n_cmd_lines = command.count("\n") + 1
    await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux send-keys -t {COACH_TMUX} {shlex.quote(f'echo {marker}A')} Enter",
        timeout_s=10)
    await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux send-keys -t {COACH_TMUX} {shlex.quote(command)} Enter",
        timeout_s=10)
    await engine.pve.agent_exec_sh(
        kali_vmid,
        f"tmux send-keys -t {COACH_TMUX} {shlex.quote(f'echo {marker}B:$?')} Enter",
        timeout_s=10)

    # -J joins wrapped lines so each typed line maps to exactly one pane line;
    # flag order matters — `-ptJ` parses as `-t J` and the capture fails
    pane_cmd = (f"tmux capture-pane -pJ -t {COACH_TMUX} -S -400 2>/dev/null "
                "| tail -200")
    # only real marker *output* lines count: `PTN…A` alone, `PTN…B:<digits>`
    begin = re.compile(rf"{re.escape(marker)}A\s*$")
    end = re.compile(rf"{re.escape(marker)}B:(\d+)\s*$")
    deadline = time.monotonic() + timeout_s
    last_tail = ""
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
            cmd_tail = command.split("\n")[-1][-60:].rstrip()
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
        if session_id and ai >= 0:
            # live output-so-far: everything after the typed command lines,
            # marker text hidden so the sentinels never reach the chat
            cmd_tail = command.split("\n")[-1][-60:].rstrip()
            typed_end = next(
                (i for i in range(len(lines) - 1, ai, -1)
                 if cmd_tail and lines[i].rstrip().endswith(cmd_tail)),
                ai + n_cmd_lines)
            tail = "\n".join(ln for ln in lines[typed_end + 1:]
                             if ln.strip() and marker not in ln)[-3000:]
            if tail != last_tail:
                last_tail = tail
                await publish_session(session_id, "coach_activity", {
                    "active": True,
                    "text": f"executing `{command[:90]}`",
                    "output": tail}, sticky=True)
        await asyncio.sleep(1.0)
    # timed out but still typed — the partial pane tail beats a dead end
    return {"out": last_tail
            or "(still running — visible in the pentrain-coach tmux window)",
            "err": ("still running — pane is now busy; further commands "
                    "bounce until it finishes or you send 'C-c'"),
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
