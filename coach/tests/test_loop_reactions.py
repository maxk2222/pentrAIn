"""Reaction-model regressions: telemetry stays silent, chat is debounced,
history/proactive-streak/welcome/vision behaviors."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach import facts as facts_mod
from coach.loop import CHAT_DEBOUNCE_S, SessionCoach


class FakeLlm:
    def __init__(self, actions=None, content="ok", tool_calls=None):
        self.calls: list[list[dict]] = []
        self.kwargs: list[dict] = []
        self.actions = actions or [{"type": "none"}]
        self.content = content
        self.tool_calls = tool_calls or []
        self.model = "fake-llm"

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        self.kwargs.append(kw)
        return {"content": self.content, "actions": self.actions,
                "tool_calls": self.tool_calls,
                "raw": {"usage": {"total_tokens": 10}}}

    async def close(self): ...


class FakeClient:
    def __init__(self, ctx=None):
        self.chats: list[dict] = []
        self.flags: list[str] = []
        self.flag_checks: list[str] = []
        self.screens = 0
        self.profiles: list[dict] = []
        self.activities: list[tuple] = []
        self.agent_pushes: list[list[dict]] = []
        self.ctx = ctx or {
            "session": {"id": 1, "state": "active", "autonomy_level": 2, "coach_enabled": True},
            "quest": {"title": "Q", "track": "web", "tier": 1, "briefing": "b",
                      "coach_context": "", "checkpoints": [], "escalation": {}},
            "flags": [], "checkpoints_hit": [], "telemetry_tail": [],
            "messages": [], "exec_count": 0, "profile": {"track_levels": {"web": 1}},
        }

    async def send_chat(self, sid, content, *, kind="chat", meta=None):
        self.chats.append({"content": content, "kind": kind, "meta": meta})
        return {}

    async def session_context(self, sid):
        return self.ctx

    async def mark_checkpoint(self, sid, cid):
        return {}

    async def suggest_command(self, sid, command, why):
        return {}

    async def stream_draft(self, sid, draft_id, content, *, reasoning="",
                           done=False, kind="chat", agent="main"):
        pass

    async def send_activity(self, sid, text="", *, active=True, agent="main"):
        self.activities.append((active, text, agent))

    async def send_agents(self, sid, agents):
        self.agent_pushes.append(agents)

    async def exec_in_kali(self, sid, command, window=None):
        self.exec_calls = getattr(self, "exec_calls", [])
        self.exec_calls.append((command, window))
        return {"out": "ok", "exitcode": 0, "visible": True}

    async def type_in_pane(self, sid, text, window=None):
        self.typed = getattr(self, "typed", [])
        self.typed.append(text)
        return {"out": "student@target01's password: \nLast login: x", "visible": True}

    async def submit_flag(self, sid, value):
        self.flags.append(value)
        return {"correct": True, "all_solved": False}

    async def check_flag(self, sid, key):
        self.flag_checks.append(key)
        return {"correct": True, "all_solved": False}

    async def capture_screen(self, sid):
        self.screens += 1
        return {"png_b64": "aGVsbG8=", "bytes": 5}

    async def update_profile(self, track_levels=None, metrics=None):
        self.profiles.append({"track_levels": track_levels, "metrics": metrics})
        return {}

    async def report_llm_usage(self, sid, model, kind, usage, latency_ms):
        return {}

    async def log_action(self, sid, tool, args, result, status="ok"):
        self.logged = getattr(self, "logged", [])
        self.logged.append({"tool": tool, "args": args, "status": status})
        return {}

    async def lesson_hit(self, lesson_id: int) -> None:
        self.hits = getattr(self, "hits", [])
        self.hits.append(lesson_id)


def _coach(cfg=None) -> tuple[SessionCoach, FakeClient]:
    c = FakeClient()
    coach = SessionCoach(1, c, cfg or {"coach": {"nudge_after_s": 60, "hint_after_s": 120},
                                     "llm": {}})
    coach.state.state = "active"
    coach.state.autonomy_level = 2
    coach.ctx = c.ctx   # populated like start() would, without wiring tasks
    return coach, c


def _cmd_event(sid: int, cmd: str) -> dict:
    return {"type": "telemetry", "topic": f"telemetry.{sid}",
            "data": {"session_id": sid, "kind": "command",
                     "payload": {"command": cmd, "ts": time.time()}}}


async def test_telemetry_never_calls_llm():
    """A flood of command events must produce zero LLM turns and zero chats."""
    coach, c = _coach()
    coach.llm = FakeLlm()
    for i in range(50):
        await coach._handle_event(_cmd_event(1, f"ls -la /tmp/f{i}"))
    assert coach.llm.calls == [] and c.chats == []
    assert len(coach.state.commands) == 50


async def test_command_result_attaches_exit_code():
    coach, _ = _coach()
    await coach._handle_event(_cmd_event(1, "nmap -sV 10.0.0.5"))
    await coach._handle_event({"type": "telemetry", "topic": "telemetry.1",
                               "data": {"session_id": 1, "kind": "command_result",
                                        "payload": {"exit_code": 1}}})
    assert coach.state.commands[-1].exit_code == 1
    assert "exit 1" in coach.state.recent_formatted(1)[0]


async def test_checkpoint_ack_uses_name():
    coach, c = _coach()
    coach.matcher = type("M", (), {
        "check": lambda self, cmd: ["c1"],
        "name_for": lambda self, cid: "Found SMB shares",
    })()
    await coach._handle_event(_cmd_event(1, "smbclient -L //10.0.0.5"))
    assert any("Found SMB shares" in m["content"] for m in c.chats)
    assert coach.state.checkpoints_hit == {"c1"}


async def test_chat_is_debounced_and_answered():
    coach, c = _coach()
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "try gobuster"}])
    coach._buffer_chat("what now?")
    coach._buffer_chat("and which list?")
    await asyncio.sleep(CHAT_DEBOUNCE_S + 0.5)
    assert len(coach.llm.calls) == 1          # one turn for both messages
    user_turn = coach.llm.calls[0][-1]["content"]
    assert "what now?" in user_turn and "which list?" in user_turn
    assert c.chats[0]["kind"] == "message"    # explicit reply, not a nudge
    # reply landed in history for future turns
    assert any(m["content"] == "try gobuster" and m["role"] == "assistant"
               for m in coach._history)


async def test_proactive_kind_and_streak():
    coach, c = _coach()
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "ping the target?"}])
    coach.state.last_progress_ts = time.time() - 5000  # deeply stuck
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    assert c.chats[0]["kind"] == "nudge"      # proactive output tagged as nudge
    assert coach.state.proactive_streak == 1
    coach.state.progress()
    assert coach.state.proactive_streak == 0  # trainee moved → reset


async def test_silent_proactive_turn_no_streak():
    coach, _ = _coach()
    coach.llm = FakeLlm(actions=[{"type": "none", "reason": "trainee is enumerating"}])
    coach.state.last_progress_ts = time.time() - 5000
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    assert coach.state.proactive_streak == 0
    # the model's reasoning becomes working memory
    assert any("enumerating" in n for n in coach.state.notes)


async def test_reflect_blocked_when_policy_denies():
    coach, _ = _coach()
    coach.llm = FakeLlm()
    coach.state.last_progress_ts = time.time()   # just made progress — no need
    await coach._reflect_tick(60)
    assert coach.llm.calls == []


async def test_ready_state_no_proactive():
    coach, _ = _coach()
    coach.state.state = "ready"
    d = coach.policy.evaluate(coach.state)
    assert not d.may_proactive


async def test_backoff_after_streak():
    coach, _ = _coach()
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "hint"}])
    coach.state.last_progress_ts = time.time() - 99999
    coach.state.last_nudge_ts = time.time() - 400  # cooldown over
    coach.state.proactive_streak = 3             # ignored 3x already
    await coach._reflect_tick(60)
    assert coach.llm.calls == []                  # still silent — backing off


async def test_exec_turn_resets_streak_instead_of_feeding_it():
    """Takeover work is progress, not an unanswered nudge — an exec turn must
    end at streak 0, not streak+1 (the bug parked working coaches in backoff)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.llm = FakeLlm(actions=[{"type": "exec_in_kali", "command": "id"}])
    coach.state.last_progress_ts = time.time() - 5000
    coach.state.last_nudge_ts = 0
    coach.state.proactive_streak = 2
    await coach._reflect_tick(60)
    assert coach.state.proactive_streak == 0

    # a chat-only proactive turn still counts toward the streak — at L4 a
    # stubborn model gets up to 4 corrective re-turns in the same tick
    # (each sees STALL_ALERT), then the cap stops the burn
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "nudge"}])
    coach.state.proactive_streak = 0
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    assert len(coach.llm.calls) == 5          # stalled turn + 4 capped re-turns
    assert coach.state.proactive_streak == 5


async def test_l4_stall_gets_one_corrective_return():
    """The L4 announce-not-act failure mode: a turn with no real work is
    retried ONCE in the same tick — the corrected turn's exec then resets
    the streak."""
    class SeqLlm(FakeLlm):
        seq = 0
        async def chat(self, messages, **kw):
            self.calls.append(messages)
            acts = ([{"type": "send_chat", "content": "will scan now"}]
                    if SeqLlm.seq == 0 else
                    [{"type": "exec_in_kali", "command": "nmap 10.1.10.21"}])
            SeqLlm.seq += 1
            return {"content": "", "actions": acts, "tool_calls": [],
                    "raw": {"usage": {"total_tokens": 10}}}
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = SeqLlm()
    coach.state.last_progress_ts = time.time() - 5000
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    assert len(coach.llm.calls) == 2          # stall → one corrective re-turn
    assert coach.state.proactive_streak == 0  # the exec reset it
    assert "STALL_ALERT" in coach.llm.calls[1][-1]["content"]


async def test_l4_busy_pane_gets_interactive_return():
    """ssh's LoginGraceTime (~120s) is shorter than the reflect cadence —
    when an exec leaves the pane busy the SAME tick must get a follow-up
    turn so the password can be typed before the connection dies."""
    class BusyLlm(FakeLlm):
        seq = 0
        async def chat(self, messages, **kw):
            self.calls.append(messages)
            acts = ([{"type": "exec_in_kali", "command": "ssh student@target01"}]
                    if BusyLlm.seq == 0 else
                    [{"type": "type_in_pane", "text": "student123"}])
            BusyLlm.seq += 1
            return {"content": "", "actions": acts, "tool_calls": [],
                    "raw": {"usage": {"total_tokens": 10}}}
    class BusyClient(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out": "student@target01's password: ",
                    "err": "still running — pane is now busy",
                    "exitcode": None, "visible": True, "timed_out": True}
        async def type_in_pane(self, sid, text, window=None):
            self.typed = getattr(self, "typed", [])
            self.typed.append(text)
            # password accepted but the pane stays inside ssh — still busy
            return {"out": "student@target01:~$ ", "visible": True,
                    "busy": True}
    coach, _c = _coach()
    coach.client = BusyClient()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = BusyLlm()
    coach.state.last_progress_ts = time.time() - 5000
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    # busy pane → chained follow-ups at LLM cadence until the cap (4
    # re-turns) — a remote shell session must not crawl at tick speed
    assert len(coach.llm.calls) == 5
    assert coach._pane_interactive is True
    assert coach.client.typed == ["student123"] * 4
    assert "interactive input pending" in coach.llm.calls[1][-1]["content"]


async def test_type_in_pane_clears_interactive_when_shell_returns():
    """The fast-path must end when our input returns the pane to a local
    shell — otherwise every reflect tick burns follow-up turns forever."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach._pane_interactive = True
    class ShellClient(FakeClient):
        async def type_in_pane(self, sid, text, window=None):
            return {"out": "root@kali:~# ", "visible": True, "busy": False}
    coach.client = ShellClient()
    did, _res = await coach._dispatch(
        {"type": "type_in_pane", "text": "exit"}, proactive=True)
    assert did and coach._pane_interactive is False


async def test_type_in_pane_dispatch_and_tool_schema():
    """Interactive panes (ssh password prompts) can't be driven by
    exec_in_kali — type_in_pane must reach the client and count as work."""
    from coach.tools import tools_for_level
    names = {t["function"]["name"] for t in tools_for_level(4)}
    assert "type_in_pane" in names
    assert "type_in_pane" not in {
        t["function"]["name"] for t in tools_for_level(3)}
    coach, c = _coach()
    coach.state.autonomy_level = 4
    did, res = await coach._dispatch(
        {"type": "type_in_pane", "text": "student123"}, proactive=True)
    assert did and c.typed == ["student123"]
    assert "password" in res
    # denied below takeover
    coach.state.autonomy_level = 3
    did, res = await coach._dispatch(
        {"type": "type_in_pane", "text": "x"}, proactive=True)
    assert not did and "denied" in res


async def test_repeat_output_gets_settled_note():
    """Re-greps of the same data come back byte-identical — the model must
    be told the facts are settled or it re-derives them forever (the
    nmap-file re-read loop seen live)."""
    class SameClient(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out": "21/tcp open  ftp\n22/tcp open  ssh",
                    "exitcode": 0, "visible": True}
    coach, _c = _coach()
    coach.client = SameClient()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _, r1 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "grep open /tmp/nmap.txt | head"},
        proactive=True)
    assert "identical" not in r1
    _, r2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /tmp/nmap.txt | grep open"},
        proactive=True)
    assert "identical" in r2 and "DIFFERENT action" in r2
    # the soft note is a hint — the 4th read of the SAME path is denied
    # outright (the model 'perfected' re-greps live instead of acting)
    _, _r3 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "grep -i open /tmp/nmap.txt"},
        proactive=True)
    did, r4 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "head /tmp/nmap.txt"},
        proactive=True)
    assert not did and "denied" in r4 and "ALREADY_DONE" in r4
    # a different path still reads fine
    did, _r5 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /etc/passwd"},
        proactive=True)
    assert did


async def test_flag_in_output_gets_submit_directive():
    """A pentrAIn{...} in exec output must trigger an immediate submit
    directive in the tool result — the model re-read flag files 3-4x to
    'confirm' them instead of submitting (observed live)."""
    class FlagClient(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out": "intern\npentrAIn{abc123def456}", "exitcode": 0,
                    "visible": True}
    coach, _c = _coach()
    coach.client = FlagClient()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _, r1 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "ssh intern@t cat user.txt"},
        proactive=True)
    assert "FLAG CAPTURED" in r1 and "pentrAIn{abc123def456}" in r1
    assert "submit_flag" in r1
    # second sight → the coach submits it itself (the model's re-read loop
    # showed the directive alone doesn't trigger the submit)
    _, r2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "ssh intern@t cat user.txt"},
        proactive=True)
    assert "AUTO-SUBMITTED" in r2 and "correct" in r2
    assert coach.client.flags == ["pentrAIn{abc123def456}"]
    # never auto-submit a value twice — even after a rejection
    coach.facts.flags["pentrAIn{abc123def456}"].submitted = True
    coach.facts.flags["pentrAIn{abc123def456}"].accepted = False
    _, r3 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat user.txt again"},
        proactive=True)
    assert "already attempted" in r3 and len(coach.client.flags) == 1


async def test_unseen_flag_submit_is_challenged_once():
    """Invented flags can never match (values are per-session) yet the model
    submits them anyway (seen live). A pentrAIn{...} value that never
    appeared in tool output is challenged once — an identical resubmit
    passes so a real-but-uncaptured read stays possible."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    did, r1 = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{invented}"}, proactive=True)
    assert not did and "unverified" in r1 and not c.flags
    did, _r2 = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{invented}"}, proactive=True)
    assert did and c.flags == ["pentrAIn{invented}"]
    # a flag that WAS seen in output submits without challenge
    coach.facts.flag_seen("pentrAIn{real}")
    did, _r3 = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{real}"}, proactive=True)
    assert did and c.flags[-1] == "pentrAIn{real}"


async def test_accepted_flag_resubmit_is_denied():
    """Resubmitting an already-accepted flag burns a turn for zero gain —
    denied before the API call (s46 submitted flag-4 four times)."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.flag_seen("pentrAIn{abc}")
    coach.facts.flag_mark_submitted("pentrAIn{abc}", True)
    did, r = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{abc}"}, proactive=True)
    assert not did and "already accepted" in r and not c.flags


async def test_activity_status_emitted_around_exec():
    """While exec_in_kali blocks in tmux the UI must show a live status —
    emitted before the call, always cleared when the dispatch loop ends."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.llm = FakeLlm(actions=[{"type": "exec_in_kali", "command": "nmap -sV 10.0.0.5"}])
    await coach._llm_turn("scan it", force_reply=True)
    starts = [t for a, t, *_ in c.activities if a]
    assert starts and "nmap" in starts[0]
    assert c.activities[-1] == (False, "", "main")


async def test_activity_cleared_when_dispatch_raises():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.llm = FakeLlm(actions=[{"type": "exec_in_kali", "command": "id"}])

    async def boom(sid, cmd, window=None):
        raise RuntimeError("backend gone")
    c.exec_in_kali = boom
    with pytest.raises(RuntimeError):
        await coach._llm_turn("go", force_reply=True)
    assert c.activities[-1] == (False, "", "main")


async def test_history_seeded_on_attach():
    ctx = FakeClient().ctx
    ctx["messages"] = [
        {"role": "coach", "content": "welcome"},
        {"role": "user", "content": "hi"},
    ]
    c = FakeClient(ctx)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    await coach.stop()
    roles = [m["role"] for m in coach._history]
    assert roles == ["user", "assistant"] or roles == ["assistant", "user"]


async def test_welcome_only_once():
    c = FakeClient()
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    await coach.stop()
    welcomes = [m for m in c.chats if "Welcome" in m["content"]]
    assert len(welcomes) == 1
    # restart: history has assistant msg → no second welcome
    c2 = FakeClient({**c.ctx, "messages": [{"role": "coach", "content": "welcome"}]})
    coach2 = SessionCoach(1, c2, {"coach": {}, "llm": {}})
    coach2.llm = FakeLlm()
    await coach2.start()
    await coach2.stop()
    assert [m for m in c2.chats if "Welcome" in m["content"]] == []


async def test_solved_writes_profile():
    coach, c = _coach()
    await coach._handle_event({"type": "state", "topic": "session.1",
                               "data": {"session_id": 1, "state": "solved"}})
    assert c.profiles and c.profiles[0]["track_levels"] == {"web": 2}


async def test_capture_screen_vision_describe():
    coach, c = _coach()
    coach._vision_model = "llava"
    coach.llm = FakeLlm(content="Terminal with a failed msfconsole is open.")
    await coach._dispatch({"type": "capture_screen"})
    assert c.screens == 1
    assert "msfconsole" in coach.state.screen_desc
    # vision call carried image content
    img_msg = coach.llm.calls[0][0]["content"]
    assert any(p.get("type") == "image_url" for p in img_msg)


async def test_capture_screen_without_vision_model():
    coach, _c = _coach()
    coach.llm = FakeLlm()
    await coach._dispatch({"type": "capture_screen"})
    assert "no vision_model" in coach.state.screen_desc
    assert coach.llm.calls == []


async def test_suggest_command_uses_content_fallback():
    coach, c = _coach()
    coach.state.autonomy_level = 3
    sent = []
    c.suggest_command = lambda sid, cmd, why: sent.append(cmd) or _noop()
    assert await coach._dispatch({"type": "suggest_command",
                                  "content": "nmap -sV 10.0.0.5"})
    assert sent == ["nmap -sV 10.0.0.5"]


async def _noop():
    return {}


# ---------- pass-2 regression tests ----------

async def test_history_seed_keeps_newest():
    """ctx messages are newest-first — the seed must keep the RECENT context."""
    msgs = [{"role": "user" if i % 2 else "coach", "content": f"m{i}"}
            for i in range(30)]  # m0 = newest
    c = FakeClient({**FakeClient().ctx, "messages": msgs})
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start(); await coach.stop()
    contents = [m["content"] for m in coach._history]
    assert "m0" in contents          # newest kept
    assert "m29" not in contents     # oldest dropped
    assert contents[0] == "m13"      # chronological: oldest of the kept slice first


async def test_attach_uses_real_telemetry_ts():
    """Replayed commands keep their real timestamps → idle isn't 'just now'."""
    old_ts = time.time() - 700
    ctx = {**FakeClient().ctx,
           "telemetry_tail": [{"kind": "command", "payload": {"command": "ls", "ts": old_ts}}],
           "session": {"id": 1, "state": "active", "autonomy_level": 2,
                       "coach_enabled": True, "started_at": "2020-01-01T00:00:00"}}
    c = FakeClient(ctx)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start(); await coach.stop()
    assert coach.state.last_activity_ts == old_ts
    assert coach.state.idle_s() > 600


async def test_fresh_attach_not_stuck_forever():
    """Progress clock seeds from session start → no stage-2 panic at attach."""
    coach, _ = _coach()
    coach.state.last_progress_ts = time.time() - 30   # session 30s old
    d = coach.policy.evaluate(coach.state)
    assert not d.may_proactive or d.stage == 0


async def test_coach_commands_dont_count_as_activity():
    """exec_in_kali output must not reset the trainee idle clock."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.state.last_activity_ts = time.time() - 1000   # trainee idle 1000s
    coach.llm = FakeLlm()
    await coach._dispatch({"type": "exec_in_kali", "command": "nmap -sV 10.0.0.5"})
    # the command echo arrives via telemetry — must be tagged from_coach
    await coach._handle_event(_cmd_event(1, "nmap -sV 10.0.0.5"))
    assert coach.state.commands[-1].from_coach
    assert coach.state.idle_s() > 900          # trainee still idle
    assert "[coach-ran]" in coach.state.recent_formatted(1)[0]


async def test_no_duplicate_user_msg_in_history():
    coach, _c = _coach()
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "answer"}])
    coach._buffer_chat("hello?")
    await asyncio.sleep(CHAT_DEBOUNCE_S + 0.5)
    users = [m for m in coach._history if m["role"] == "user" and "hello?" in m["content"]]
    assert len(users) == 1


async def test_quick_ack_visible_to_model():
    coach, _ = _coach()
    await coach._quick_ack("Flag `root` accepted.")
    assert any("accepted" in m["content"] and m["role"] == "assistant"
               for m in coach._history)


async def test_wrong_flag_ack_cooldown():
    coach, c = _coach()
    ev = lambda: {"type": "flag", "topic": "session.1",
                  "data": {"session_id": 1, "correct": False}}
    await coach._handle_event(ev())
    await coach._handle_event(ev())
    await coach._handle_event(ev())
    nacks = [m for m in c.chats if "isn't right" in m["content"]]
    assert len(nacks) == 1


async def test_capture_screen_rate_limited():
    coach, c = _coach()
    coach._vision_model = "v"
    coach.llm = FakeLlm(content="x")
    await coach._dispatch({"type": "capture_screen"})
    await coach._dispatch({"type": "capture_screen"})
    await coach._dispatch({"type": "capture_screen"})
    assert c.screens == 1


async def test_disabled_coach_notice_once():
    coach, c = _coach()
    coach.state.coach_enabled = False
    ev = lambda: {"type": "coach_message", "topic": "coach.1",
                  "data": {"session_id": 1, "role": "user", "content": "help?"}}
    await coach._handle_event(ev())
    await coach._handle_event(ev())
    notices = [m for m in c.chats if "disabled" in m["content"]]
    assert len(notices) == 1
    assert coach.state.pending_chat == []


async def test_apply_cfg_rebuilds_policy_and_llm():
    coach, _ = _coach()
    old_llm = coach.llm
    await coach.apply_cfg({"coach": {"nudge_after_s": 1, "hint_after_s": 2,
                                     "verbosity": "terse"},
                           "llm": {"model": "new-model"}})
    assert coach.policy.nudge_s == int(1 * 1.6)   # terse factor applied
    assert coach.llm is not old_llm
    assert coach.llm.model == "new-model"


async def test_force_reply_recorded_in_history():
    coach, _ = _coach()
    coach.llm = FakeLlm(actions=[{"type": "none"}], content="free text answer")
    await coach._llm_turn("q", force_reply=True)
    assert any(m["role"] == "assistant" and "free text" in m["content"]
               for m in coach._history)


async def test_stage_passed_to_context():
    """Policy stage (not nudges_sent) reaches the prompt."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    msg = build_context_msg(coach.ctx, coach.state, "test", "high",
                            stage=2, action_budget=7)
    assert "escalation_stage=2" in msg
    assert "0/7 execs" in msg


async def test_coach_cmd_marker_suffix_still_matches():
    """tmux wraps commands with ` ; echo PTNxxx:$?` — telemetry echoes the
    wrapped line; it must still be recognized as coach-issued."""
    coach, _c = _coach()
    coach._coach_cmds.append(("nmap -sV 10.0.0.5", time.time()))
    await coach._handle_event(_cmd_event(
        1, "nmap -sV 10.0.0.5 ; echo PTNabc12:$?"))
    # exec_in_kali self-records at dispatch — the telemetry echo of the same
    # (marker-suffixed) line is recognized and NOT added a second time
    assert coach.state.commands == []


async def test_terminal_session_attach_returns_false():
    ctx = {**FakeClient().ctx,
           "session": {"state": "solved", "autonomy_level": 2, "coach_enabled": True}}
    c = FakeClient(ctx)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    assert await coach.start() is False


async def test_replay_pairs_exit_codes():
    ctx = {**FakeClient().ctx,
           "telemetry_tail": [  # newest-first from backend
               {"kind": "command_result", "payload": {"exit_code": 1}},
               {"kind": "command", "payload": {"command": "nmap x", "ts": 100}}]}
    c = FakeClient(ctx)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start(); await coach.stop()
    assert coach.state.commands[-1].exit_code == 1


# ---------- pass-3 regression tests ----------

async def test_ghost_session_attach_returns_false():
    """Backend 404 → empty ctx → no phantom coach."""
    c = FakeClient({"session": {}, "quest": {}})
    coach = SessionCoach(999, c, {"coach": {}, "llm": {}})
    assert await coach.start() is False


async def test_denied_exec_does_not_stale_match():
    """A denied exec leaves no _coach_cmds entry → identical user cmd isn't
    mislabeled as coach-issued."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    c.exec_in_kali = lambda sid, cmd, window=None: _denied()
    await coach._dispatch({"type": "exec_in_kali", "command": "rm -rf /"})
    assert coach._coach_cmds == []                       # entry removed
    coach.state.last_activity_ts = time.time() - 500
    await coach._handle_event(_cmd_event(1, "rm -rf /"))  # user typed it themselves
    assert not coach.state.commands[-1].from_coach


async def _denied():
    return {"status": "denied", "error": "guardrails"}


async def test_exec_count_only_on_real_exec():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    c.exec_in_kali = lambda sid, cmd, window=None: _denied()
    await coach._dispatch({"type": "exec_in_kali", "command": "x"})
    assert coach.state.exec_count == 0


async def test_empty_send_chat_sends_nothing():
    coach, c = _coach()
    spoke, _ = await coach._dispatch({"type": "send_chat", "content": "   "})
    assert spoke is False
    assert c.chats == []


async def test_mark_checkpoint_validates_known_ids():
    coach, c = _coach()
    marked = []
    c.mark_checkpoint = lambda sid, cid: marked.append(cid) or _noop()
    coach.matcher = type("M", (), {
        "check": lambda self, cmd: [], "name_for": lambda self, cid: cid,
        "_rules": [("c1", "n", None)],
    })()
    await coach._dispatch({"type": "mark_checkpoint", "checkpoint_id": "bogus"})
    assert marked == []
    await coach._dispatch({"type": "mark_checkpoint", "checkpoint_id": "c1"})
    assert marked == ["c1"]


async def test_resync_merges_backend_state():
    coach, c = _coach()
    c.ctx = {**c.ctx,
             "session": {"id": 1, "state": "active", "autonomy_level": 3,
                         "coach_enabled": True},
             "checkpoints_hit": ["c9"],
             "flags": [{"key": "root", "solved": True}]}
    await coach.resync()
    assert coach.state.autonomy_level == 3
    assert coach.state.checkpoints_hit == {"c9"}
    assert coach.state.flags_solved == {"root"}


async def test_feed_ignored_after_stop():
    coach, _c = _coach()
    await coach.stop()
    await coach.feed(_cmd_event(1, "ls"))
    assert coach._queue.empty()


async def test_hint_level_clamped():
    coach, c = _coach()
    await coach._dispatch({"type": "offer_hint", "content": "h", "level": 99})
    assert c.chats[0]["meta"]["level"] == 3


# ---------- anti-repeat context ----------

async def test_context_lists_done_commands_at_l4():
    """At takeover autonomy the model needs the OPERATOR framing plus a
    visible list of already-succeeded commands (stops re-verify loops)."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    st.add_command(1.0, "getent hosts api01", from_coach=True)
    st.commands[-1].exit_code = 0
    st.add_command(2.0, "getent hosts api01", from_coach=True)   # repeat, still running
    st.add_command(3.0, "nmap bad-target", from_coach=True)
    st.commands[-1].exit_code = 1                              # failed — not "done"
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "OPERATOR" in msg and "no trainee" in msg
    assert "ALREADY_DONE" in msg
    assert "getent hosts api01" in msg.split("ALREADY_DONE")[1]
    assert "nmap bad-target" not in msg.split("ALREADY_DONE")[1]


async def test_context_stall_alert_at_l4():
    """Chat-only turns at L4 must surface as a stall alert — announcing a
    plan is the observed failure mode (model chats forever, never execs)."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "STALL_ALERT" not in msg          # no stall yet
    st.proactive_streak = 2
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "STALL_ALERT" in msg and "exec_in_kali" in msg


async def test_context_recon_saturation_at_l4():
    """Recon-variant loops (nmap -sV → -sT → -O → -p-) are a real failure
    mode — the context must call saturation once a target is scanned 3x."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    st.add_command(1.0, "nmap -sV 10.1.10.21", from_coach=True)
    st.add_command(2.0, "nmap -p- 10.1.10.21", from_coach=True)
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "RECON_SATURATED" not in msg                  # 2 scans is fine
    st.add_command(3.0, "nmap -O 10.1.10.21", from_coach=True)
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "RECON_SATURATED" in msg and "10.1.10.21" in msg
    # trainee's own scans don't count toward saturation
    st2 = coach.state
    st2.commands.clear()
    st2.add_command(1.0, "nmap x", from_coach=False)
    msg = build_context_msg(coach.ctx, st2, "takeover loop", stage=1)
    assert "RECON_SATURATED" not in msg


async def test_context_plan_staleness_nudge():
    """L4 + real work + missing/stale plan → the context must push
    update_plan (costs no exec budget). Below L4 or early turns: silent."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    st.exec_count = 20
    # empty plan → nudge line
    msg = build_context_msg(coach.ctx, st, "x", stage=1)
    assert "PLAN: none — set one via update_plan" in msg
    # fresh plan → normal render, no stale marker
    st.plan = [{"t": "hunt flag-4", "s": "doing"}]
    st.plan_updated = time.time()
    msg = build_context_msg(coach.ctx, st, "x", stage=1)
    assert "hunt flag-4" in msg and "stale" not in msg
    # stale plan → marker on the title
    st.plan_updated = time.time() - 1000
    msg = build_context_msg(coach.ctx, st, "x", stage=1)
    assert "stale: refresh via update_plan" in msg
    # below L4 the staleness marker stays silent (the plan itself may render)
    coach.ctx["session"]["autonomy_level"] = 2
    msg = build_context_msg(coach.ctx, st, "x", stage=1)
    assert "stale:" not in msg and "PLAN: none" not in msg


async def test_budget_warning_suffix():
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    st = coach.state
    st.exec_count = 10
    msg = build_context_msg(coach.ctx, st, "x", stage=1, action_budget=50)
    assert "nearly exhausted" not in msg
    st.exec_count = 42
    msg = build_context_msg(coach.ctx, st, "x", stage=1, action_budget=50)
    assert "42/50" in msg and "nearly exhausted" in msg


async def test_report_flag_visible_in_context():
    """s46-P7 regression: the briefing's report deliverable + the report
    flag's name must both survive context truncation."""
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    briefing = Path(
        __file__).resolve().parents[2] / \
        "content/packs/capstone/cap-t2-nordmarkt/briefing.md"
    coach.ctx["quest"]["briefing"] = briefing.read_text()
    coach.ctx["flags"] = [
        {"key": "report", "name": "Assessment report (kali: /root/report.md)",
         "points": 100, "solved": False}]
    msg = build_context_msg(coach.ctx, coach.state, "x", stage=1)
    assert "/root/report.md" in msg and "Assessment report" in msg


async def test_update_plan_sets_plan_updated():
    coach, _c = _l4_coach()
    assert coach.state.plan_updated == 0.0
    await coach._dispatch({"type": "update_plan",
                           "items": [{"t": "next", "s": "doing"}]})
    assert coach.state.plan_updated > 0


async def test_flag_solve_auto_marks_plan_steps():
    """s65: 'doing: retrieve ftp flag' stayed open 40 actions AFTER the flag
    was submitted — a solve retires its own roadmap steps."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.state.plan = [{"t": "Retrieve ftp flag from /ftp/flag1.txt", "s": "doing"},
                        {"t": "Submit ftp flag value", "s": "todo"},
                        {"t": "SQLi login bypass on /rest/user/login", "s": "todo"}]

    async def submit(sid, value):
        return {"correct": True, "flag_key": "ftp-flag", "all_solved": False}
    c.submit_flag = submit
    coach.facts.flags["pentrAIn{x}"] = facts_mod.FlagFact(seen=1)
    _, result = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{x}"}, proactive=True)
    plan = coach.state.plan
    assert plan[0]["s"] == "done" and plan[1]["s"] == "done"
    assert plan[2]["s"] == "todo"     # unrelated step stays open
    assert "auto-marked" in result


async def test_flag_solve_auto_marks_generic_numbered_keys():
    """s84: flag key 'flag-1' has NO distinctive token — normalized-key
    matching must still retire 'Solve flag-1' while leaving 'flag-2' open,
    and the first solve retires the recon step too."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.state.plan = [
        {"t": "Recon: nmap all targets", "s": "doing"},
        {"t": "Solve flag-1", "s": "todo"},
        {"t": "Solve flag-2, flag-3, flag-4", "s": "todo"}]

    async def submit(sid, value):
        return {"correct": True, "flag_key": "flag-1", "all_solved": False}
    c.submit_flag = submit
    coach.facts.flags["pentrAIn{x}"] = facts_mod.FlagFact(seen=1)
    _, result = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{x}"}, proactive=True)
    plan = coach.state.plan
    assert plan[0]["s"] == "done"    # recon retired by first solve
    assert plan[1]["s"] == "done"    # normalized 'flag1' match
    assert plan[2]["s"] == "todo"    # 'flag-2/3/4' step stays open
    assert "auto-marked" in result


async def test_check_flag_solve_auto_marks_and_closes_on_all_solved():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.state.plan = [{"t": "View admin section", "s": "doing"},
                        {"t": "Loot leftovers", "s": "todo"}]

    async def chk(sid, key):
        return {"correct": True, "flag_key": key, "all_solved": True}
    c.check_flag = chk
    _, result = await coach._dispatch(
        {"type": "check_flag", "flag_key": "admin-section-flag"}, proactive=True)
    assert all(i["s"] == "done" for i in coach.state.plan)
    assert "plan closed" in result


async def test_stale_plan_reminder_rides_tool_results():
    """The context-block 'stale' suffix is advisory — under exec pressure the
    model never sees it (s65: 40+ actions on a dead plan). The reminder must
    ride the channel it always reads: tool results."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.state.exec_count = 20
    coach.state.plan = [{"t": "stuck step", "s": "doing"}]
    coach.state.plan_updated = time.time() - 2000
    _, result = await coach._dispatch({"type": "none", "reason": "thinking"})
    assert "PLAN NOTE" in result and "update_plan" in result
    # throttled — once per staleness window, not every action
    _, result2 = await coach._dispatch({"type": "none", "reason": "again"})
    assert "PLAN NOTE" not in result2


async def test_missing_plan_reminder_after_real_work():
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.state.exec_count = 20
    _, result = await coach._dispatch({"type": "none", "reason": "x"})
    assert "no roadmap" in result


async def test_identical_plan_resave_reports_unchanged():
    """s64 spammed 3 identical plans in a row — an unchanged rewrite should
    say so instead of 'saved' so the model stops re-sending it."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    items = [{"t": "step a", "s": "doing"}, {"t": "step b", "s": "todo"}]
    _, r1 = await coach._dispatch({"type": "update_plan", "items": items})
    _, r2 = await coach._dispatch({"type": "update_plan", "items": items})
    assert "plan saved" in r1 and "unchanged" in r2


async def test_context_trainee_framing_below_l4():
    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 2
    msg = build_context_msg(coach.ctx, coach.state, "stuck", stage=0)
    assert "trainee progressing" in msg and "OPERATOR" not in msg


def test_done_commands_dedup_and_order():
    from coach.state import SessionState
    st = SessionState(1)
    st.add_command(1.0, "id", from_coach=True); st.commands[-1].exit_code = 0
    st.add_command(2.0, "ls", from_coach=False); st.commands[-1].exit_code = 0
    st.add_command(3.0, "id", from_coach=True); st.commands[-1].exit_code = 0
    st.add_command(4.0, "id", from_coach=True)                 # no exit yet
    assert st.done_commands() == ["id"]          # dedup + only coach + exit 0


def test_written_files_detects_heredoc_and_filters():
    from coach.state import SessionState
    st = SessionState(1)
    st.add_command(1.0, "cat > /root/solve.py << 'PYEOF'\nimport x\nPYEOF",
                   from_coach=True); st.commands[-1].exit_code = 0
    st.add_command(2.0, "curl -s http://x 2>&1 | tee /tmp/out.txt",
                   from_coach=True); st.commands[-1].exit_code = 0
    st.add_command(3.0, "cat > /dev/null", from_coach=True)
    st.commands[-1].exit_code = 0
    st.add_command(3.5, "cat /tmp/rt.txt 2>/dev/null || echo NO",
                   from_coach=True)                                   # stderr discard — not a write
    st.commands[-1].exit_code = 0
    st.add_command(4.0, "cat > /root/fail.sh", from_coach=True)
    st.commands[-1].exit_code = 1                          # failed write — no file
    st.add_command(5.0, "cat > /root/solve.py << 'V2'", from_coach=True)
    st.commands[-1].exit_code = 0                          # rewrite — still dedup
    assert st.written_files() == ["/root/solve.py", "/tmp/out.txt"]


async def test_rewrite_same_path_appends_directive():
    """Second write to the same path → tool result carries a RUN directive."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    cmd = "cat > /root/solve.py << 'EOF'\nimport x\nEOF"
    _v1, r1 = await coach._dispatch({"type": "exec_in_kali", "command": cmd})
    assert "RUN it" not in r1
    _v2, r2 = await coach._dispatch({"type": "exec_in_kali", "command": cmd})
    assert "RUN it" in r2 and "/root/solve.py" in r2


async def test_rewrite_guard_denies_third_write_without_failed_run():
    """A script written ≥2× that never ran (or ran clean) is DENIED — the
    model must run it; a failed run unlocks the rewrite again."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    w = "cat > /root/solve.py << 'EOF'\nimport x\nEOF"
    for _ in range(2):
        await coach._dispatch({"type": "exec_in_kali", "command": w})
    n_execs = len([a for a in c.chats if a.get("kind") == "action_report"])
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert r.startswith("denied:") and "never executed" in r
    # nothing was typed → no new action_report
    assert len([a for a in c.chats if a.get("kind") == "action_report"]) == n_execs
    # run it, fail → rewrite allowed again
    async def _fail(sid, cmd, window=None):
        return {"out": "boom", "exitcode": 1, "visible": True}
    c.exec_in_kali = _fail
    await coach._dispatch({"type": "exec_in_kali", "command": "python3 -u /root/solve.py"})
    # dispatch recorded the failure via facts bookkeeping
    assert coach.facts.files["/root/solve.py"].last_exit == 1
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert not r.startswith("denied:")


async def test_rewrite_unlocked_by_run_or_failed_check():
    """s54 live: report.sh ran clean but its output was wrong — the guard
    must allow write->run->inspect->rewrite. Only a version never
    exercised since its last write stays denied."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    w = "cat > /root/report.sh << 'EOF'\nx\nEOF"
    for _ in range(2):
        await coach._dispatch({"type": "exec_in_kali", "command": w})
    # run the current version cleanly → it produced observable output
    await coach._dispatch({"type": "exec_in_kali", "command": "bash /root/report.sh"})
    assert coach.facts.files["/root/report.sh"].last_exit == 0
    # the rewrite after seeing that output is informed iteration → allowed
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert not r.startswith("denied:")
    # ...and a never-run new version is denied again
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert r.startswith("denied:") and "never executed" in r
    # a failed check also counts as fresh evidence → unlocks
    coach.facts.checkfail_seq += 1
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert not r.startswith("denied:")


async def test_rewrite_guard_skips_cron_executed_file():
    """A file whose root-cron execution is a proven caps: fact CAN'T be run
    by the agent — 'RUN it now' is a dead end there (s46: backup.sh written
    2x, cron ran it as root, third payload-write got denied anyway)."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.facts.caps.append("root-exec via /opt/shop/backup.sh@shop01")
    w = "cat > /opt/shop/backup.sh << 'EOF'\ncp /root/flag.txt /tmp/f\nEOF"
    for _ in range(2):
        await coach._dispatch({"type": "exec_in_kali", "command": w})
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert not r.startswith("denied:")


async def test_start_seeds_write_counts_from_replay():
    """Coach restart mid-session: replayed writes must seed facts.files so
    the rewrite guard stays armed — otherwise each restart resets it."""
    ctx = {**FakeClient().ctx,
           "session": {"id": 1, "state": "active", "autonomy_level": 4,
                       "coach_enabled": True},
           "telemetry_tail": [   # newest-first, like the backend serves it
               {"kind": "command_result", "payload": {"exit_code": 0}},
               {"kind": "command", "payload": {
                   "command": "cat > /root/solve.py << 'EOF'\ny\nEOF", "ts": 101}},
               {"kind": "command_result", "payload": {"exit_code": 0}},
               {"kind": "command", "payload": {
                   "command": "cat > /root/solve.py << 'EOF'\nx\nEOF", "ts": 100}},
           ]}
    c = FakeClient(ctx)
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start(); await coach.stop()
    assert coach.facts.files["/root/solve.py"].writes == 2
    # third write denied immediately — no free rewrites after restart
    coach2 = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach2.llm = FakeLlm()
    await coach2.start()
    _v, r = await coach2._dispatch({"type": "exec_in_kali",
                                    "command": "cat > /root/solve.py << 'EOF'\nz\nEOF"})
    assert r.startswith("denied:")
    await coach2.stop()


async def test_context_operator_directive_at_l4():
    """User chat at L4 must surface as OPERATOR_DIRECTIVE in the takeover
    context — session 30 showed the model ignoring operator nudges for ~7
    turns because they only existed as role=user history entries."""
    import time

    from coach.prompts import build_context_msg
    coach, _ = _coach()
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "OPERATOR_DIRECTIVE" not in msg          # none buffered yet
    st.operator_directive = "run ssh -tt for the pager"
    st.operator_directive_ts = time.time()
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "OPERATOR_DIRECTIVE" in msg and "ssh -tt" in msg
    # stale directives expire — don't boss the model around forever
    st.operator_directive_ts = time.time() - 700
    msg = build_context_msg(coach.ctx, st, "takeover loop", stage=1)
    assert "OPERATOR_DIRECTIVE" not in msg


# ---------- in-turn agentic chain (act→observe→act) ----------

def _call(i: int, name: str, args: str = "{}") -> dict:
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": args}}


class ScriptLlm(FakeLlm):
    """Returns a scripted sequence of responses — one per llm.chat call."""
    def __init__(self, resps):
        super().__init__()
        self.resps = list(resps)

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        r = self.resps.pop(0) if self.resps else {
            "content": "", "actions": [{"type": "none"}], "tool_calls": []}
        r.setdefault("raw", {"usage": {"total_tokens": 5}})
        return r


async def test_inturn_chain_feeds_tool_results_back():
    """A tool_call's result must go straight back into the SAME turn — the
    next llm.chat sees the exec output instead of waiting ~90s for the
    next reflect tick."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = ScriptLlm([
        {"content": "", "tool_calls": [_call(1, "exec_in_kali")],
         "actions": [{"type": "exec_in_kali", "command": "id",
                      "_call_id": "c1"}]},
        {"content": "done", "tool_calls": [_call(2, "send_chat")],
         "actions": [{"type": "send_chat", "content": "done",
                      "_call_id": "c2"}]},
    ])
    await coach._llm_turn("work", proactive=True)
    assert len(coach.llm.calls) == 2          # both calls inside ONE turn
    # second call's message list carries the tool reply pairing for c1
    second = coach.llm.calls[1]
    tools = [m for m in second if m.get("role") == "tool"]
    assert any(t.get("tool_call_id") == "c1" and "ok" in t["content"]
               for t in tools)
    # pairing rule intact: assistant message carries the raw tool_calls
    assert any(m.get("role") == "assistant" and m.get("tool_calls")
               for m in second)


async def test_chain_stops_on_no_work_calls():
    """send_chat/none-only responses end the chain — the model decided to
    talk, not to act; forcing another call would burn tokens for prose."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = ScriptLlm([
        {"content": "", "tool_calls": [_call(1, "none")],
         "actions": [{"type": "none", "reason": "waiting",
                      "_call_id": "c1"}]},
    ])
    await coach._llm_turn("work", proactive=True)
    assert len(coach.llm.calls) == 1


async def test_chain_respects_chain_max():
    coach, _c = _coach({"coach": {"takeover_chain_max": 3}, "llm": {}})
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    exec_resp = {"content": "", "tool_calls": [_call(1, "exec_in_kali")],
                 "actions": [{"type": "exec_in_kali", "command": "id",
                              "_call_id": "c1"}]}
    coach.llm = ScriptLlm([dict(exec_resp) for _ in range(10)])
    await coach._llm_turn("work", proactive=True)
    assert len(coach.llm.calls) == 3          # capped — not 10


async def test_chain_preempted_by_pending_chat():
    """A buffered trainee message must release the llm lock after the
    current sub-call — chat answers can't queue behind a 12-call chain."""
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    exec_resp = {"content": "", "tool_calls": [_call(1, "exec_in_kali")],
                 "actions": [{"type": "exec_in_kali", "command": "id",
                              "_call_id": "c1"}]}
    coach.llm = ScriptLlm([dict(exec_resp) for _ in range(10)])
    coach.state.pending_chat = ["stop and explain"]   # arrived mid-turn
    await coach._llm_turn("work", proactive=True)
    assert len(coach.llm.calls) == 1          # broke after the first sub-call


async def test_autonomy_event_switches_level_live():
    """The /autonomy chat command and UI toggle broadcast a session.* event —
    the running coach must apply it immediately, not on the next resync."""
    coach, _ = _coach()
    coach._next_reflect = time.monotonic() + 9999
    await coach._handle_event({"type": "autonomy", "topic": "session.1",
                               "data": {"session_id": 1, "level": 4}})
    assert coach.state.autonomy_level == 4
    assert coach.ctx["session"]["autonomy_level"] == 4
    # takeover switch while active → reflect pulled to ~now
    assert coach._next_reflect < time.monotonic() + 60


async def test_autonomy_event_downgrade_does_not_nudge():
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach._next_reflect = time.monotonic() + 9999
    await coach._handle_event({"type": "autonomy", "topic": "session.1",
                               "data": {"session_id": 1, "level": 2}})
    assert coach.state.autonomy_level == 2
    assert coach._next_reflect > time.monotonic() + 60  # untouched


async def test_policy_takeover_pace_gates_new_chains():
    """Between work chains the model still gets a short settle — the pace
    setting, not the 90s trainee cooldown, paces L4 chain starts."""
    from coach.policy import Policy
    from coach.state import SessionState
    st = SessionState(session_id=1)
    st.state = "active"
    st.coach_enabled = True
    st.autonomy_level = 4
    st.last_progress_ts = time.time()
    p = Policy({}, nudge_s=480, hint_s=900, takeover_pace_s=10)
    st.last_nudge_ts = time.time() - 5
    assert not p.evaluate(st).may_proactive      # inside the 10s settle
    st.last_nudge_ts = time.time() - 15
    assert p.evaluate(st).may_proactive          # past it → next chain fires


async def test_foreign_ip_guard():
    """Hallucinated target IPs (session 31: 10.42.0.5 invented from kali's
    10.1.10.5) hang every connect. Commands may only carry IPs inside a
    target /24, seen in earlier output, or public."""
    c = FakeClient()
    c.ctx["quest"]["targets"] = [{"name": "svc01", "ip": "10.1.10.25"}]
    c.ctx["session"]["autonomy_level"] = 4
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "curl http://10.42.0.5/x"})
    assert r.startswith("denied:") and "10.42.0.5" in r and "10.1.10.25" in r
    # same /24 as the target (router, sibling VMs) passes
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "ping -c1 10.1.10.254"})
    assert not r.startswith("denied:")
    # public IP passes (internet uplink)
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "curl -sI https://8.8.8.8"})
    assert not r.startswith("denied:")
    # an IP seen in tool output becomes allowed (pivot-safe)
    await coach._scan_flags("nmap done: discovered host 172.16.5.10")
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "nmap 172.16.5.10"})
    assert not r.startswith("denied:")
    await coach.stop()


async def test_foreign_ip_no_self_seeding():
    """A hallucinated IP must never whitelist itself: its own error output
    ('Failed to connect to 10.42.0.5') echoes the command line — intent, not
    discovery. Only IPs appearing in output but NOT in the command are real
    discoveries (session 39 regression)."""
    c = FakeClient()
    c.ctx["quest"]["targets"] = [{"name": "dvwa01", "ip": "10.1.10.21"}]
    c.ctx["session"]["autonomy_level"] = 4
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    # simulate: the hallucinated command ran once (e.g. before targets
    # resolved) and its error output echoed the bad IP back
    coach.facts.observe_output(
        "curl -s http://10.42.0.5/dvwa/",
        "curl: (7) Failed to connect to 10.42.0.5 port 80: No route to host",
        7)
    assert "10.42.0.5" not in coach.facts.ips_seen
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "curl http://10.42.0.5/dvwa/"})
    assert r.startswith("denied:")
    # but a genuinely discovered IP/subnet (in output only, never in a
    # command) still whitelists — the pivot case the guard exists for
    coach.facts.observe_output(
        "ssh edge 'ip route'",
        "default via 10.2.0.1 dev eth1\n10.2.0.0/24 dev eth1", 0)
    await coach._scan_flags(
        "default via 10.2.0.1 dev eth1\n10.2.0.0/24 dev eth1",
        "ssh edge 'ip route'")
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "nmap 10.2.0.5"})
    assert not r.startswith("denied:")
    await coach.stop()


async def test_lan_scope_is_enforced_by_ip_guard():
    """Home-lab mode: the authorized CIDR seeds allowed_nets — in-scope IPs
    pass, out-of-scope PRIVATE ips are a hard deny (real ROE for L4, not
    just a prompt line)."""
    c = FakeClient()
    c.ctx["quest"]["targets"] = [{"name": "lan-scope",
                                  "ip": "192.168.3.131/24"}]
    c.ctx["quest"]["scope"] = "192.168.3.0/24"
    c.ctx["session"]["autonomy_level"] = 4
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    coach.llm = FakeLlm()
    await coach.start()
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "ping -c1 192.168.3.50"})
    assert not r.startswith("denied:")          # inside the authorized CIDR
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "nmap -sn 10.0.0.0/24"})
    assert r.startswith("denied:")              # out-of-scope private → ROE
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "curl -sI https://8.8.8.8"})
    assert not r.startswith("denied:")          # public uplink stays open
    await coach.stop()


# ---------------- parallel worker agents (L4 subagents) ----------------

class _WorkerScriptLlm(FakeLlm):
    """Scripted LLM — worker prompts (system line mentions 'worker agent')
    get a two-beat script: one exec, then a plain report. Parent calls
    stay silent so the test sees only worker activity."""

    def __init__(self):
        super().__init__()
        self.worker_calls = 0

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        if "worker agent" in (messages[0].get("content") or ""):
            self.worker_calls += 1
            if self.worker_calls == 1:
                return {"content": "",
                        "reasoning": "probe the NAS for services first",
                        "actions": [{"type": "exec_in_kali",
                                     "command": "nmap -sV 192.168.3.55",
                                     "_call_id": "c1"}],
                        "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {
                                            "name": "exec_in_kali",
                                            "arguments": "{}"}}],
                        "raw": {"usage": {"total_tokens": 1}}}
            return {"content": "REPORT: 22/80 open, anonymous share listed",
                    "reasoning": "both ports are interesting — wrapping up",
                    "actions": [{"type": "none", "reason": "task done"}],
                    "tool_calls": [],
                    "raw": {"usage": {"total_tokens": 1}}}
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


class _StallLlm(FakeLlm):
    """Worker never finishes — for kill/status/collect-timeout tests."""
    async def chat(self, messages, **kw):
        if "worker agent" in (messages[0].get("content") or ""):
            await asyncio.sleep(60)
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


def _l4_coach():
    c = FakeClient()
    c.ctx["session"]["autonomy_level"] = 4
    c.ctx["session"]["subagents_enabled"] = True
    c.ctx["quest"]["targets"] = [{"name": "nas", "ip": "192.168.3.55"}]
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    return coach, c


async def test_spawn_runs_worker_on_own_pane_and_reports():
    coach, c = _l4_coach()
    await coach.start()
    coach.llm = _WorkerScriptLlm()   # after start(): it rebuilds llm from cfg
    _v, r = await coach._dispatch({"type": "spawn_agent",
                                   "task": "enumerate the NAS"})
    assert "spawned w1" in r
    await asyncio.sleep(0.2)            # worker runs its two beats
    # its exec went to its OWN window — never the parent pane
    assert ("nmap -sV 192.168.3.55", "w1") in c.exec_calls
    # every chat line the worker posted (exec report, final report) is
    # tagged meta.agent="w1" so the UI files it under that agent's feed —
    # nothing worker-related leaks into the main transcript
    worker_msgs = [m for m in c.chats
                   if (m.get("meta") or {}).get("agent") == "w1"]
    main_msgs = [m for m in c.chats
                 if not (m.get("meta") or {}).get("agent")]
    assert any("nmap" in m["content"] for m in worker_msgs)
    assert all(not m["content"].startswith("[w") for m in main_msgs)
    # the roster chips learned about w1 (spawn push + finish push)
    assert any(a["id"] == "w1" for push in c.agent_pushes for a in push)
    assert c.agent_pushes[-1][0]["status"] == "done"
    _v, r = await coach._dispatch({"type": "collect_agent",
                                   "worker_id": "w1"})
    assert "w1 done" in r and "REPORT: 22/80" in r
    await coach.stop()


async def test_spawn_report_links_to_worker_feed():
    """The parent's spawn confirmation in the main chat carries agent_ref —
    the UI renders it as a jump link into the worker's feed."""
    coach, c = _l4_coach()
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    await coach._dispatch({"type": "spawn_agent", "task": "enum"})
    spawn_msg = next(m for m in c.chats if "Spawned" in m["content"])
    assert spawn_msg["meta"]["agent_ref"] == "w1"
    assert "agent" not in spawn_msg["meta"]   # it stays in the MAIN feed
    await coach.stop()


async def test_worker_activity_and_report_are_agent_scoped():
    """Worker activity ticks and its closing report are tagged with its id;
    its inactive event only clears ITS chip — never the parent's."""
    coach, c = _l4_coach()
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    await coach._dispatch({"type": "spawn_agent", "task": "enum"})
    await asyncio.sleep(0.2)
    # every activity tick carries an agent tag
    assert all(len(t) == 3 for t in c.activities)
    worker_ticks = [t for t in c.activities if t[2] == "w1"]
    assert worker_ticks
    # finished → w1's activity explicitly cleared, tagged with w1
    assert (False, "", "w1") in c.activities
    # and the closing report landed in ITS feed with its reasoning
    reports = [m for m in c.chats
               if (m.get("meta") or {}).get("agent") == "w1"
               and "REPORT" in m["content"]]
    assert reports and reports[0]["meta"]["reasoning"]
    await coach.stop()


class _FlakyWorkerLlm(FakeLlm):
    """Worker LLM that raises bare exceptions (like httpx.ReadTimeout, whose
    str() is empty) — first N calls fail, then the normal two-beat script."""

    def __init__(self, fails: int, exc: Exception):
        super().__init__()
        self.fails = fails
        self.exc = exc
        self.worker_calls = 0

    async def chat(self, messages, **kw):
        if "worker agent" in (messages[0].get("content") or ""):
            self.worker_calls += 1
            if self.worker_calls <= self.fails:
                raise self.exc
            if self.worker_calls == self.fails + 1:
                return {"content": "",
                        "actions": [{"type": "exec_in_kali",
                                     "command": "id", "_call_id": "c1"}],
                        "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {"name": "exec_in_kali",
                                                     "arguments": "{}"}}],
                        "raw": {"usage": {"total_tokens": 1}}}
            return {"content": "REPORT: recovered after transient llm error",
                    "actions": [{"type": "none"}],
                    "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}
        return {"content": "", "actions": [{"type": "none"}],
                "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}


async def test_worker_transient_llm_error_retries_once():
    """A single bare exception (ReadTimeout-style) must not kill the
    worker — one retry, then it continues normally."""
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = _FlakyWorkerLlm(fails=1, exc=TimeoutError())
    await coach._dispatch({"type": "spawn_agent", "task": "enum"})
    await asyncio.sleep(0.4)
    assert coach._workers["w1"].status == "done"
    assert "recovered" in coach._workers["w1"].report
    await coach.stop()


async def test_worker_crash_report_names_exception_type():
    """Empty-str exceptions (httpx timeouts) must still produce a useful
    report: exception type + last output, never 'worker crashed: '."""
    coach, c = _l4_coach()
    await coach.start()
    coach.llm = _FlakyWorkerLlm(fails=99, exc=TimeoutError())
    await coach._dispatch({"type": "spawn_agent", "task": "enum"})
    await asyncio.sleep(0.4)
    w = coach._workers["w1"]
    assert w.status == "failed"
    assert "TimeoutError" in w.report
    assert w.report != "worker crashed: "
    # the failure report still landed in the worker's own feed
    reports = [m for m in c.chats
               if (m.get("meta") or {}).get("agent") == "w1"
               and "crashed" in m["content"]]
    assert reports
    await coach.stop()


async def test_spawn_denied_when_subagents_off():
    c = FakeClient()
    c.ctx["session"]["autonomy_level"] = 4
    coach = SessionCoach(1, c, {"coach": {}, "llm": {}})
    await coach.start()
    coach.llm = FakeLlm()
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "x"})
    assert r.startswith("denied:")
    await coach.stop()


async def test_worker_cap_denies_over_limit():
    coach, _c = _l4_coach()
    coach.cfg["coach"]["max_workers"] = 1
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "a"})
    assert "spawned w1" in r
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "b"})
    assert r.startswith("denied:")
    await coach.stop()


async def test_worker_context_blocks_nonexec_tools():
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    _v, r = await coach._dispatch({"type": "send_chat", "content": "hi"},
                                  window="w1")
    assert r.startswith("denied:")      # workers may not talk to the trainee
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "id"}, window="w1")
    assert not r.startswith("denied:")
    await coach.stop()


async def test_subagents_off_kills_running_workers():
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = _StallLlm()
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "x"})
    assert "spawned w1" in r
    await coach._handle_event({"type": "subagents", "topic": "session.1",
                               "data": {"enabled": False, "session_id": 1}})
    assert coach.state.subagents_enabled is False
    assert coach._workers["w1"].status == "killed"
    await coach.stop()


async def test_autonomy_downgrade_kills_workers():
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = _StallLlm()
    await coach._dispatch({"type": "spawn_agent", "task": "x"})
    await coach._handle_event({"type": "autonomy", "topic": "session.1",
                               "data": {"level": 3, "session_id": 1}})
    assert coach._workers["w1"].status == "killed"
    await coach.stop()


async def test_collect_running_returns_status_not_block():
    coach, _c = _l4_coach()
    coach.cfg["coach"]["collect_wait_s"] = 0.1
    await coach.start()
    coach.llm = _StallLlm()
    await coach._dispatch({"type": "spawn_agent", "task": "x"})
    _v, r = await coach._dispatch({"type": "collect_agent",
                                   "worker_id": "w1"})
    assert "still running" in r
    await coach.stop()


async def test_agent_status_lists_workers():
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    _v, r = await coach._dispatch({"type": "agent_status"})
    assert "no workers" in r
    await coach._dispatch({"type": "spawn_agent", "task": "x"})
    _v, r = await coach._dispatch({"type": "agent_status"})
    assert "w1" in r
    await coach.stop()


def test_subagent_tools_gated_by_flag():
    from coach.tools import tools_for_level
    plain = {t["function"]["name"] for t in tools_for_level(4)}
    assert "spawn_agent" not in plain
    on = {t["function"]["name"]
          for t in tools_for_level(4, subagents=True)}
    assert {"spawn_agent", "collect_agent", "agent_status",
            "kill_agent"} <= on
    l3 = {t["function"]["name"]
          for t in tools_for_level(3, subagents=True)}
    assert "spawn_agent" not in l3


async def test_collect_merges_json_report_into_facts():
    """A worker's closing JSON report lands in the parent FactsDB — creds,
    hosts, ports — not just as prose in the tool result."""
    class JsonWorkerLlm(FakeLlm):
        async def chat(self, messages, **kw):
            if "worker agent" in (messages[0].get("content") or ""):
                return {"content": '{"summary": "share found",'
                        ' "creds": [{"user": "svc", "secret": "s3cr3t",'
                        '            "host": "192.168.3.55"}],'
                        ' "hosts": [{"ip": "192.168.3.55", "name": "nas",'
                        '            "ports": {"445": "smb"}}],'
                        ' "findings": ["anonymous share readable"],'
                        ' "next": "mount and loot"}',
                        "actions": [{"type": "none", "reason": "done"}],
                        "tool_calls": [],
                        "raw": {"usage": {"total_tokens": 1}}}
            return {"content": "", "actions": [{"type": "none"}],
                    "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = JsonWorkerLlm()
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "enum nas"})
    assert "spawned w1" in r
    await asyncio.sleep(0.2)
    _v, r = await coach._dispatch({"type": "collect_agent",
                                   "worker_id": "w1"})
    # the report merged at finish time — collect reads it without re-merging
    assert "facts already merged" in r
    assert any(c.user == "svc" and c.secret == "s3cr3t"
               for c in coach.facts.creds)
    assert coach.facts.hosts["192.168.3.55"].ports == {445: "smb"}
    assert "anonymous share readable" in coach.facts.findings
    await coach.stop()


async def test_collect_prose_report_still_extracts():
    """Fallback: a prose report yields facts via the generic parser."""
    class ProseWorkerLlm(FakeLlm):
        async def chat(self, messages, **kw):
            if "worker agent" in (messages[0].get("content") or ""):
                return {"content": "REPORT: ssh svc:s3cr3t works on "
                        "192.168.3.55; flag in /root/flag.txt",
                        "actions": [{"type": "none", "reason": "done"}],
                        "tool_calls": [],
                        "raw": {"usage": {"total_tokens": 1}}}
            return {"content": "", "actions": [{"type": "none"}],
                    "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}
    coach, _c = _l4_coach()
    await coach.start()
    coach.llm = ProseWorkerLlm()
    await coach._dispatch({"type": "spawn_agent", "task": "enum nas"})
    await asyncio.sleep(0.2)
    _v, r = await coach._dispatch({"type": "collect_agent",
                                   "worker_id": "w1"})
    # prose report extracted at finish; collect just echoes it back —
    # generic extraction keeps the discovered host from the text
    assert "facts already merged" in r
    assert "192.168.3.55" in coach.facts.hosts
    await coach.stop()


async def test_finished_worker_frees_its_slot():
    coach, _c = _l4_coach()
    coach.cfg["coach"]["max_workers"] = 1
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "a"})
    assert "spawned w1" in r
    await asyncio.sleep(0.2)          # worker finishes its two beats
    assert coach._workers["w1"].status == "done"
    _v, r = await coach._dispatch({"type": "spawn_agent", "task": "b"})
    assert "spawned w1" in r          # the done slot is reusable
    await coach.stop()


async def test_worker_execs_do_not_drain_parent_budget():
    """Worker execs are bounded by their own turn/time caps — they must
    neither consume the parent's action_budget nor be denied by it (a busy
    worker pool would otherwise hard-deny the parent's own chain)."""
    coach, _c = _l4_coach()
    coach.cfg["coach"]["action_budget"] = 1
    coach.cfg["coach"]["action_grace"] = 0
    await coach.start()
    coach.llm = _WorkerScriptLlm()
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "id"}, window="w1")
    assert not r.startswith("denied:")
    assert coach.state.exec_count == 0      # parent's budget untouched
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "id"})
    assert not r.startswith("denied:")
    assert coach.state.exec_count == 1
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "id"})
    assert r.startswith("denied:")          # parent hits its own cap …
    _v, r = await coach._dispatch({"type": "exec_in_kali",
                                   "command": "id"}, window="w1")
    assert not r.startswith("denied:")      # … but workers still run
    await coach.stop()


async def test_worker_budget_low_wrapup_produces_report():
    """Approaching its caps the worker gets ONE 'report now' injection —
    it finishes done with a structured report instead of a timeout
    output-tail."""
    class NeverDoneLlm(FakeLlm):
        def __init__(self):
            super().__init__()
            self.saw_wrapup = False

        async def chat(self, messages, **kw):
            if "worker agent" in (messages[0].get("content") or ""):
                if any("BUDGET LOW" in (m.get("content") or "")
                       for m in messages):
                    self.saw_wrapup = True
                    return {"content": '{"summary": "partial: 22/80 open"}',
                            "actions": [{"type": "none", "reason": "wrap"}],
                            "tool_calls": [],
                            "raw": {"usage": {"total_tokens": 1}}}
                return {"content": "",
                        "actions": [{"type": "exec_in_kali",
                                     "command": "id", "_call_id": "c1"}],
                        "tool_calls": [{"id": "c1", "type": "function",
                                        "function": {
                                            "name": "exec_in_kali",
                                            "arguments": "{}"}}],
                        "raw": {"usage": {"total_tokens": 1}}}
            return {"content": "", "actions": [{"type": "none"}],
                    "tool_calls": [], "raw": {"usage": {"total_tokens": 1}}}

    coach, _c = _l4_coach()
    coach.cfg["coach"]["worker_turn_cap"] = 4
    coach.cfg["coach"]["worker_time_cap_s"] = 900
    await coach.start()
    llm = NeverDoneLlm()
    coach.llm = llm
    await coach._dispatch({"type": "spawn_agent", "task": "enum"})
    await asyncio.sleep(0.4)
    w = coach._workers["w1"]
    assert llm.saw_wrapup              # wrap-up turn actually reached it
    assert w.status == "done"          # graceful exit, not a timeout
    assert "partial: 22/80" in w.report
    await coach.stop()


async def test_busy_bounces_escalate_to_wedge_directive():
    """Two consecutive execs that never finished (bounced off a held pane
    or still running) must escalate to a hard C-c/type_in_pane directive —
    session 25 burned 3+ turns trying command variants on a wedged curl."""
    class Wedged(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out": "", "err": "pane busy: 'curl'",
                    "busy": True, "visible": False}
    coach, _c = _coach()
    coach.client = Wedged()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _v, r1 = await coach._dispatch({"type": "exec_in_kali",
                                    "command": "curl http://t/x"}, proactive=True)
    assert "PANE_WEDGED" not in r1
    _v, r2 = await coach._dispatch({"type": "exec_in_kali",
                                    "command": "curl --max-time 5 http://t/x"},
                                   proactive=True)
    assert "PANE_WEDGED" in r2 and "C-c" in r2 and "type_in_pane" in r2
    assert coach._busy_bounces.get("main") == 2


async def test_busy_bounces_reset_on_type_and_exit():
    """Answering the prompt (type_in_pane) or a clean exit must reset the
    wedge counter — only *consecutive* unfinished execs escalate."""
    class Toggle(FakeClient):
        busy = True
        async def exec_in_kali(self, sid, command, window=None):
            if self.busy:
                return {"out": "", "err": "pane busy", "busy": True}
            return {"out": "done", "exitcode": 0, "visible": True}
    coach, _c = _coach()
    coach.client = Toggle()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    await coach._dispatch({"type": "exec_in_kali", "command": "x"}, proactive=True)
    assert coach._busy_bounces.get("main") == 1
    await coach._dispatch({"type": "type_in_pane", "text": "pw"}, proactive=True)
    assert coach._busy_bounces.get("main") == 0
    coach.client.busy = False
    await coach._dispatch({"type": "exec_in_kali", "command": "x"}, proactive=True)
    assert coach._busy_bounces.get("main") == 0


async def test_busy_bounces_are_per_pane():
    """A worker's wedged window must not escalate the parent's counter —
    bounce state is tracked per pane, not globally."""
    class Wedged(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            if window:
                return {"out": "", "err": "pane busy", "busy": True}
            return {"out": "done", "exitcode": 0, "visible": True}
    coach, _c = _coach()
    coach.client = Wedged()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    await coach._dispatch({"type": "exec_in_kali", "command": "x"},
                          window="w1")
    await coach._dispatch({"type": "exec_in_kali", "command": "y"},
                          window="w1")
    assert coach._busy_bounces.get("w1") == 2
    assert not coach._busy_bounces.get("main")
    # the parent's clean pane sees no escalation from the worker's wedge
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": "id"})
    assert "PANE_WEDGED" not in r


async def test_operator_directive_clears_after_first_action():
    """A pinned OPERATOR_DIRECTIVE that was acted on must stop steering —
    otherwise stale directives train the model to ignore the block."""
    import time
    coach, _c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    st = coach.state
    st.operator_directive = "submit the flag you saw"
    st.operator_directive_ts = time.time()
    await coach._dispatch({"type": "exec_in_kali", "command": "ls"},
                          proactive=True)
    assert st.operator_directive == ""


async def test_context_includes_reference_and_tool_inventory():
    """TRACK_REFERENCE/QUEST_REFERENCE/KALI_TOOLS must render — the cheatsheet
    tool syntax + live inventory are the coach's knowledge base."""
    from coach.prompts import build_context_msg
    coach, _c = _coach()
    coach.ctx["quest"]["track_cheatsheet"] = "nmap -sV <ip>\nsmbclient -N -L"
    coach.ctx["quest"]["cheatsheet"] = "quest-local note"
    coach.ctx["session_tools"] = "nmap\nsmbclient\nmysql"
    msg = build_context_msg(coach.ctx, coach.state, "takeover loop")
    assert "TRACK_REFERENCE:" in msg and "smbclient -N -L" in msg
    assert "QUEST_REFERENCE:" in msg and "quest-local note" in msg
    assert "KALI_TOOLS" in msg and "mysql" in msg


async def test_dropped_history_distills_into_earlier():
    """HISTORY_CAP overflow must leave a trace — the rolling EARLIER summary
    keeps long-horizon runs from losing their early turns entirely."""
    from coach.loop import HISTORY_CAP
    coach, _c = _coach()
    for i in range(HISTORY_CAP + 6):
        coach._record_reply(f"assistant message {i}")
    assert len(coach._history) <= HISTORY_CAP
    assert coach.state.earlier
    assert any(l.startswith("said:") and "message 0" in l
               for l in coach.state.earlier)
    # bounded — a 400-turn run can't grow it
    for i in range(60):
        coach._record_reply(f"x{i}")
    assert len(coach.state.earlier) <= 10
    # and it renders into the context
    from coach.prompts import build_context_msg
    coach.state.autonomy_level = 4
    msg = build_context_msg(coach.ctx, coach.state, "t", stage=0,
                            facts=coach.facts)
    assert "EARLIER" in msg


async def test_reseed_marks_submitted_flags():
    """flag_submits in ctx → accepted/rejected values survive restart."""
    coach, c = _l4_coach()
    c.ctx["flag_submits"] = [
        {"value": "pentrAIn{good}", "correct": True},
        {"value": "pentrAIn{bad}", "correct": False}]
    await coach.start()
    assert coach.facts.flags["pentrAIn{good}"].accepted
    assert coach.facts.flags["pentrAIn{good}"].submitted
    assert coach.facts.flags["pentrAIn{bad}"].submitted
    assert not coach.facts.flags["pentrAIn{bad}"].accepted
    await coach.stop()


async def test_reseed_merges_worker_reports():
    """Finished worker reports flow back into FACTS on re-attach."""
    coach, c = _l4_coach()
    c.ctx["worker_reports"] = [{
        "agent": "w1",
        "content": '{"summary":"nas enum","creds":[{"user":"svc",'
                   '"secret":"s3","host":"192.168.3.55"}],'
                   '"findings":["share readable"]}'}]
    await coach.start()
    assert any(cr.secret == "s3" for cr in coach.facts.creds)
    assert "share readable" in coach.facts.findings
    await coach.stop()


async def test_reseed_fills_out_sigs():
    """Identical post-restart output hits 'settled facts' immediately."""
    coach, c = _l4_coach()
    c.ctx["coach_outputs"] = [
        {"command": "cat /tmp/x", "out": "same content\nline2", "exitcode": 0}]
    await coach.start()
    # sig for the replayed output is already counted once → the next
    # identical exec reports NOTE: identical output (n>=2)
    _spoke, _res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /tmp/x"})
    # FakeClient returns 'ok' output — different sig, so run once more
    # checking the seeded sig directly instead:
    import hashlib
    sig = hashlib.sha1(
        "\n".join(l.strip() for l in "same content\nline2".splitlines()
                  if l.strip())[:1500].encode()).hexdigest()[:12]
    assert coach._out_sigs.get(sig, 0) >= 1
    await coach.stop()


async def test_reread_guard_uses_persistent_fact_reads():
    """Guard counts facts.files[path].reads — survives restarts because
    the replay feeds observe_output (no more in-memory _read_counts)."""
    coach, c = _l4_coach()
    c.ctx["coach_outputs"] = [
        {"command": "cat /etc/creds.txt", "out": "u=p", "exitcode": 0},
        {"command": "cat /etc/creds.txt", "out": "u=p", "exitcode": 0},
        {"command": "cat /etc/creds.txt", "out": "u=p", "exitcode": 0}]
    await coach.start()
    assert coach.facts.files["/etc/creds.txt"].reads == 3
    _spoke, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /etc/creds.txt"})
    assert res.startswith("denied:") and "already read 3x" in res
    await coach.stop()


async def test_reseed_plan_and_notes():
    """plan + coach_notes in ctx → agent intent survives restart."""
    coach, c = _l4_coach()
    c.ctx["plan"] = [{"t": "cron privesc via backup.sh", "s": "done"},
                     {"t": "LOAD_FILE flag via shop_ro", "s": "doing"},
                     {"t": "bogus", "s": "not-a-status"}]
    c.ctx["coach_notes"] = ["ssh pivot via deploy@shop01 works",
                            "api token nm-api-9f3d77c1"]
    await coach.start()
    assert coach.state.plan[0]["s"] == "done"
    assert coach.state.plan[1]["s"] == "doing"
    assert coach.state.plan[2]["s"] == "todo"      # normalized on reseed
    assert coach.state.notes == ["ssh pivot via deploy@shop01 works",
                                 "api token nm-api-9f3d77c1"]
    await coach.stop()


async def test_reseed_orphaned_workers_become_notes():
    """worker_orphans in ctx → a note tells the parent a worker's task died
    with the restart (outputs already reseed via coach_outputs — s46's
    post-restart 'file on wrong host' confusion)."""
    coach, c = _l4_coach()
    c.ctx["coach_notes"] = ["existing note"]
    c.ctx["worker_orphans"] = [
        {"agent": "w1", "task": "modify /opt/shop/backup.sh on shop01"}]
    await coach.start()
    orphan = [n for n in coach.state.notes if "died with a coach restart" in n]
    assert len(orphan) == 1 and "w1" in orphan[0]
    assert "backup.sh" in orphan[0] and "FACTS" in orphan[0]
    # orphan note lands AFTER ctx notes — freshest, therefore rendered
    assert coach.state.notes[-1] == orphan[0]
    await coach.stop()


async def test_plan_renders_in_context():
    from coach.prompts import build_context_msg
    coach, c = _l4_coach()
    coach.ctx = c.ctx
    coach.state.plan = [{"t": "loot init.sql", "s": "done"},
                        {"t": "mysql LOAD_FILE", "s": "doing"}]
    msg = build_context_msg(coach.ctx, coach.state, "t", stage=0,
                            facts=coach.facts)
    assert "PLAN" in msg and "[x] loot init.sql" in msg
    assert "[>] mysql LOAD_FILE" in msg
    # empty plan renders nothing — context stays lean
    coach.state.plan = []
    msg = build_context_msg(coach.ctx, coach.state, "t", stage=0,
                            facts=coach.facts)
    assert "PLAN" not in msg


async def test_worker_prompt_carries_operator_plan():
    from coach.prompts import render_worker_prompt
    coach, c = _l4_coach()
    coach.ctx = c.ctx
    coach.state.plan = [{"t": "parent next step", "s": "doing"}]
    from coach.loop import _Worker
    w = _Worker(id="w1", task="t")
    from coach.prompts import plan_render
    p = render_worker_prompt(coach.ctx, w, "FACTS-x",
                             plan_render(coach.state.plan,
                                         title="OPERATOR_PLAN"))
    assert "OPERATOR_PLAN" in p and "parent next step" in p
    assert "update_plan" in p        # worker rule line present


async def test_coach_enabled_event_pauses_and_resumes():
    """The /sessions/{id}/coach broadcast must idle the loop live —
    resync-only would let a 'paused' agent finish its current plan."""
    coach, _c = _l4_coach()
    await coach.start()
    assert coach.state.coach_enabled
    coach._workers["w1"] = _mk_worker()          # pause kills workers
    ev = lambda en: {"type": "coach_enabled", "topic": "session.1",
                     "session_id": 1, "data": {"enabled": en}}
    await coach._handle_event(ev(False))
    assert not coach.state.coach_enabled
    assert coach._workers["w1"].status == "killed"
    assert coach.ctx["session"]["coach_enabled"] is False
    # a paused coach must not answer chat either — it buffers nothing
    await coach._handle_event({"type": "coach_message",
                               "topic": "coach.1", "session_id": 1,
                               "data": {"role": "user", "content": "hi"}})
    assert not coach.state.pending_chat
    await coach._handle_event(ev(True))
    assert coach.state.coach_enabled
    assert coach._next_reflect < time.monotonic() + 2   # thinks soon
    await coach.stop()


def _mk_worker():
    import time as _t

    from coach.loop import _Worker
    return _Worker(id="w1", task="t", started=_t.monotonic())


async def test_l4_attach_seeds_plan_scaffold_from_flags():
    """s61/s65/s66: 40-70 actions, zero update_plan calls — the checklist
    only works if it exists. At L4 attach with no persisted plan, seed a
    flag-keyed scaffold the model then owns/rewrites."""
    coach, c = _l4_coach()
    c.ctx["flags"] = [{"key": "web-flag", "solved": False},
                      {"key": "root-flag", "solved": False},
                      {"key": "old-flag", "solved": True}]
    await coach.start()
    texts = [i["t"] for i in coach.state.plan]
    assert coach.state.plan[0]["s"] == "doing" and "Recon" in texts[0]
    assert any("web-flag" in t for t in texts)
    assert any("root-flag" in t for t in texts)
    assert not any("old-flag" in t for t in texts)      # solved → excluded
    assert any("Verify" in t for t in texts)
    await asyncio.sleep(0)   # let the seed card/persist tasks run
    cards = [m for m in c.chats if "Plan (seeded)" in m["content"]]
    assert cards and cards[0]["meta"]["plan"][0]["s"] == "doing"
    assert any(a["tool"] == "update_plan" and
               a["args"].get("auto") == "seeded" for a in c.logged)
    await coach.stop()


async def test_l2_attach_does_not_seed_plan():
    coach, c = _coach()
    c.ctx["flags"] = [{"key": "f1", "solved": False}]
    await coach.start()
    assert coach.state.plan == []
    await coach.stop()


async def test_persisted_plan_beats_seed():
    coach, c = _l4_coach()
    c.ctx["flags"] = [{"key": "f1", "solved": False}]
    c.ctx["plan"] = [{"t": "my own roadmap", "s": "doing"}]
    await coach.start()
    assert [i["t"] for i in coach.state.plan] == ["my own roadmap"]
    await coach.stop()


async def test_seeded_plan_auto_marks_on_flag_solve():
    coach, c = _l4_coach()
    c.ctx["flags"] = [{"key": "web-flag", "solved": False}]
    await coach.start()
    async def sub(sid, value):
        return {"correct": True, "flag_key": "web-flag", "all_solved": False}
    c.submit_flag = sub
    coach.facts.flags["pentrAIn{x}"] = facts_mod.FlagFact(seen=1)
    _, _result = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{x}"}, proactive=True)
    assert any("web-flag" in i["t"] and i["s"] == "done"
               for i in coach.state.plan)
    await asyncio.sleep(0)   # card push is fire-and-forget
    cards = [m for m in c.chats if m["meta"] and m["meta"].get("auto") == "auto-mark"]
    assert cards and cards[0]["meta"]["plan"]
    await coach.stop()


async def test_restart_reconciles_plan_against_solved_flags():
    """Solves under a dead coach never got auto-marks — on start() the
    restored plan must retire matching steps (s84: card showed flag-1
    'todo' after a coach restart). Recon stays open: a previous-attempt
    solve says nothing about this run's enumeration."""
    coach, c = _l4_coach()
    c.ctx["plan"] = [{"t": "Recon: nmap all targets", "s": "doing"},
                     {"t": "Solve flag-1", "s": "todo"},
                     {"t": "Solve flag-2", "s": "todo"}]
    c.ctx["flags"] = [{"key": "flag-1", "solved": True},
                      {"key": "flag-2", "solved": False}]
    await coach.start()
    plan = coach.state.plan
    assert plan[0]["s"] == "doing"   # recon NOT auto-retired on restart
    assert plan[1]["s"] == "done"
    assert plan[2]["s"] == "todo"
    await asyncio.sleep(0)
    assert any(m["meta"] and m["meta"].get("auto") == "reconciled"
               for m in c.chats)
    await coach.stop()


async def test_missing_plan_note_fires_early():
    """exec gate dropped to >=3 — the no-roadmap note must not wait for 15
    execs while the run drifts planless."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.state.exec_count = 3
    _, result = await coach._dispatch({"type": "none", "reason": "x"})
    assert "no roadmap" in result
    coach.state.exec_count = 2
    coach._plan_stale_ping = 0.0
    _, result = await coach._dispatch({"type": "none", "reason": "x"})
    assert "no roadmap" not in result


async def test_filtered_host_denial_rides_the_tool_result():
    """A scan proving every port filtered must add a blocked: fact AND a
    NOTE on the tool result itself — a worker's facts snapshot is frozen
    at spawn, so only this guaranteed-read channel can stop rescan loops
    (s84: w1 burned 4 nmap variants on an isolated app01)."""
    class FilteredClient(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out":
                    "Nmap scan report for app01 (10.1.10.32)\n"
                    "Host is up (0.00030s latency).\n"
                    "PORT     STATE    SERVICE\n"
                    "21/tcp   filtered ftp\n"
                    "22/tcp   filtered ssh\n"
                    "80/tcp   filtered http\n"
                    "443/tcp  filtered https\n"
                    "3306/tcp filtered mysql\n"
                    "5432/tcp filtered postgresql\n"
                    "Nmap done: 1 IP address (1 host up) scanned",
                    "exitcode": 0, "visible": True}
    coach, _ = _coach()
    coach.client = FilteredClient()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "nmap -sV -p- 10.1.10.32"},
        proactive=True)
    assert did
    assert "filtered:10.1.10.32@kali" in coach.facts.denials
    assert "NOTE: 10.1.10.32 is unreachable/filtered from kali" in res
    assert "pivot" in res
    # the note fires ONCE per denial — a re-scan may not re-spam it
    did, res2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "echo probing"},
        proactive=True)
    assert "unreachable/filtered" not in res2


async def test_lookup_guide_dispatch_returns_module_body():
    """lookup_guide is the pull half of the knowledge system — the recipe
    lands in the tool reply, speaks nothing to the trainee, costs no exec."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _did, res = await coach._dispatch(
        {"type": "lookup_guide", "query": "git-leak"}, proactive=True)
    assert "zlib.decompress" in res          # verbatim recipe reached the reply
    _did, res = await coach._dispatch(
        {"type": "lookup_guide", "query": "bogus-mod"}, proactive=True)
    assert "error: unknown guide" in res and "pivoting" in res


async def test_guide_trigger_hint_fires_once_per_module():
    """The deterministic push: output matching a module's triggers appends
    a GUIDE hint to the tool result — exactly once per module, so a weak
    model doesn't have to know what to search for."""
    class GitClient(FakeClient):
        async def exec_in_kali(self, sid, command, window=None):
            return {"out": "Index of /.git/  Parent Directory  logs/ objects/",
                    "exitcode": 0, "visible": True}
    coach, _ = _coach()
    coach.client = GitClient()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "curl -s http://web01/.git/"}, proactive=True)
    assert "GUIDE: module 'git-leak'" in res
    assert 'lookup_guide("git-leak")' in res
    _, res2 = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "curl -s http://web01/.git/logs/"}, proactive=True)
    assert "GUIDE:" not in res2              # once per module — no spam


async def test_filtered_and_missing_denials_hard_deny():
    """filtered:/missing: denials join unreachable: as hard exec denies —
    a hinted dead end was still retried if the model ignored FACTS."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials += ["filtered:10.1.10.32@kali",
                            "missing:curl@web01"]
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sC -p- 10.1.10.32"}, proactive=True)
    assert not did and "filtered:10.1.10.32@kali" in res
    # a different vantage is NOT covered by the kali-vantage denial
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'nmap -sV 10.1.10.32'"},
        proactive=True)
    assert did
    # missing tool on the pivot host denies only that tool@host pair
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'curl -s http://10.1.10.33/'"},
        proactive=True)
    assert not did and "missing:curl@web01" in res
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "curl -s http://10.1.10.33/"},
        proactive=True)
    assert did                               # curl on kali is fine


async def test_denials_scope_local_vs_remote():
    """missing:/capability denials must only see the REMOTE part of an
    ssh pivot — `sshpass -p x ssh u@web01 'expect ...'` runs sshpass on
    KALI, so missing:sshpass@web01 must NOT brick the correct two-hop
    pivot (observed live: the agent was denied 4x mid-pivot)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials += ["missing:sshpass@web01",
                            "denied:sudo@web01",
                            "missing:curl@kali"]
    # sshpass on KALI → free (this exact shape was bricked in s84)
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'x' ssh -o StrictHostKeyChecking=no "
                    "deploy@web01 'expect -c \"spawn ssh app01\"'"},
        proactive=True)
    assert did, res
    # sshpass in the REMOTE tail → still denied
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'sshpass -p x ssh app@app01'"},
        proactive=True)
    assert not did and "missing:sshpass@web01" in res
    # but sshpass as PAYLOAD is the fix, not a use — scp the binary onto
    # the host to install it must pass (s84 live: the agent's workaround
    # for missing:sshpass@web01 got bricked by the guard itself)
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "scp /usr/bin/sshpass deploy@web01:/tmp/sshpass"},
        proactive=True)
    assert did, res
    # and a local path argument that merely names the tool stays free too
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'cat /tmp/sshpass.md5'"},
        proactive=True)
    assert did, res
    # sudo on KALI before the ssh → free; sudo in the remote tail → denied
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sudo sshpass -p x ssh deploy@web01 'id'"},
        proactive=True)
    assert did, res
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'sudo id'"}, proactive=True)
    assert not did and "denied:sudo@web01" in res
    # missing:*@kali sees only the LOCAL head — remote curls stay free
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'curl -s http://app01/'"},
        proactive=True)
    assert did, res
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "curl -s http://app01/"},
        proactive=True)
    assert not did and "missing:curl@kali" in res
    # auth denials still match the local invocation incl. the token
    coach.facts.denials.append("denied:ssh-root@web01")
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh -o StrictHostKeyChecking=no root@web01"},
        proactive=True)
    assert not did and "denied:ssh-root@web01" in res
    # …but a different user@web01 stays free
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "ssh deploy@web01 'id'"},
        proactive=True)
    assert did, res


async def test_remote_vantage_ip_not_pinned_to_kali():
    """A connect run via python ON web01 must not be denied by a kali-scoped
    filtered fact — the IP lives in the remote tail's quoted code, and a
    naive `;`-split fabricated local segments out of it (s84: the working
    urllib pivot to app01's inventory API got bricked mid-run)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials += ["filtered:10.1.10.32@kali"]
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'x' ssh deploy@web01 'python3 -c \"import "
                    "urllib.request; r=urllib.request.Request("
                    "\\\"http://10.1.10.32:8080/x\\\"); "
                    "print(urllib.request.urlopen(r))\"'"},
        proactive=True)
    assert did, res
    # but a kali-local connect to the same ip still denies
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "curl -s http://10.1.10.32:8080/x"},
        proactive=True)
    assert not did and "filtered:10.1.10.32@kali" in res


async def test_filtered_denies_connect_attempts_not_just_scans():
    """filtered:ip@vantage = EVERY port dead from that vantage — connect
    verbs (ssh/curl/ping) to the ip are the same dead end as rescans
    (s84 burned repeated 15-20s timeouts on ssh to a fully-filtered ip)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials.append("filtered:10.1.10.32@kali")
    for verb in ("ssh deploy@10.1.10.32 'whoami'",
                 "curl -s http://10.1.10.32:8080/",
                 "ping -c1 10.1.10.32",
                 "nc -zv 10.1.10.32 22"):
        did, res = await coach._dispatch(
            {"type": "exec_in_kali", "command": verb}, proactive=True)
        assert not did and "filtered:10.1.10.32@kali" in res, verb
    # a -J hop THROUGH web01 to the filtered ip is the legitimate pivot —
    # filtered:@kali only proves the DIRECT path dead, so it stays free…
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh -J deploy@web01 deploy@10.1.10.32 'id'"},
        proactive=True)
    assert did, res
    # …but filtered:@web01 covers exactly that hop: the ip sits in
    # web01's remote tail as a bare user@ip token (no connect verb needed)
    coach.facts.denials.append("filtered:10.1.10.32@web01")
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh -J deploy@web01 deploy@10.1.10.32 'id'"},
        proactive=True)
    assert not did and "filtered:10.1.10.32@web01" in res
    # but a command merely MENTIONING the ip stays free
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "grep 10.1.10.32 /tmp/notes.txt"}, proactive=True)
    assert did, res


async def test_denials_see_pipe_segments_as_fresh_local_context():
    """`ssh u@a 'x' | sshpass ssh u@b 'y'` — the second command is a NEW
    local invocation, not remote-on-a (s84: key-copy pipe to app01 got
    denied by missing:sshpass@web01 with the wrong reason while the real
    dead end — the direct connect to filtered app01 — went unseen)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials += ["missing:sshpass@web01",
                            "filtered:10.1.10.32@kali"]
    pipe = ("sshpass -p x ssh deploy@web01 'cat ~/.ssh/id_rsa.pub' "
            "| sshpass -p x ssh deploy@10.1.10.32 'mkdir -p ~/.ssh'")
    # segment2 runs locally on kali — sshpass@web01 must not see it…
    # …but filtered:app01@kali sees the direct connect in segment2's head
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": pipe}, proactive=True)
    assert not did and "filtered:10.1.10.32@kali" in res
    # without the filtered fact the pipe is a legit two-hop chain
    coach.facts.denials.remove("filtered:10.1.10.32@kali")
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": pipe}, proactive=True)
    assert did, res


async def test_scan_saturation_denies_variant_rescans():
    """Three+ recon scans on a host with zero open ports = settled — the
    next flag-variant scan is denied even without a filtered: denial
    (e.g. scans that return 'host seems down' produce no port lines)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    h = coach.facts.add_host("10.1.10.32")
    h.scans = 3
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -A -p- 10.1.10.32"}, proactive=True)
    assert not did and "scanned 3x" in res and "pivot" in res
    # a host with discovered ports is NOT saturated — targeted rescans ok
    h2 = coach.facts.add_host("10.1.10.21")
    h2.scans = 4
    h2.ports[22] = "ssh"
    did, _res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sV -p 22,80 10.1.10.21"}, proactive=True)
    assert did


async def test_record_lesson_persists_agent_knowledge():
    """record_lesson is the agent's own knowledge channel — lands in
    FACTS.lessons (rendered to parent + workers) and logs for restart
    replay. Answers 'can the agent create knowledge': yes, session-scoped."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _did, res = await coach._dispatch(
        {"type": "record_lesson",
         "text": "app01 needs Bearer token from /portal/config.js"},
        proactive=True)
    assert "lesson recorded" in res
    assert any("Bearer token" in l for l in coach.facts.lessons)
    assert "lessons:" in coach.facts.render()
    # worker-tagged lessons carry their source
    _did, _res = await coach._dispatch(
        {"type": "record_lesson", "text": "db01 reachable only via app01"},
        proactive=True, window="w1")
    assert any(l.startswith("[w1]") for l in coach.facts.lessons)
    # the action is audited for restart replay (log_action is fire-and-
    # forget — let the scheduled task run first)
    await asyncio.sleep(0)
    assert any(l["tool"] == "record_lesson" for l in c.logged)
    _did, res = await coach._dispatch(
        {"type": "record_lesson", "text": ""}, proactive=True)
    assert "error: empty lesson" in res


async def test_lessons_replay_after_restart():
    """ctx['lessons'] rows (logged record_lesson actions) restore into
    FactsDB.lessons on attach — the model's distilled session knowledge
    survives restarts like every other fact type."""
    coach, _c = _coach()
    coach.ctx["lessons"] = [
        {"text": "web01 .git still mirrored at /tmp/nordwind-objects",
         "agent": "main"},
        {"text": "app01 api needs X-Token header", "agent": "w1"}]
    for lt in coach.ctx["lessons"]:
        coach.facts.add_lesson(str(lt.get("text") or ""),
                               str(lt.get("agent") or "main"))
    assert len(coach.facts.lessons) == 2
    rendered = coach.facts.render()
    assert "lessons:" in rendered and "[w1]" in rendered


async def test_observer_hint_queued_then_injected_once():
    """observer_hint event → pending queue → lands on the NEXT tool result
    (guaranteed-read), pop-once, labeled unverified."""
    coach, _c = _coach()
    await coach._handle_event({"type": "observer_hint", "topic": "session.1",
                               "session_id": 1,
                               "data": {"text": "try gobuster --timeout"}})
    assert coach.state.pending_observer_hints == ["try gobuster --timeout"]
    _s, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "ls /tmp"}, proactive=True)
    assert "OBSERVER (unverified): try gobuster --timeout" in res
    # drained — second result carries no hint
    _s, res2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "ls /tmp"}, proactive=True)
    assert "OBSERVER" not in res2


async def test_field_note_tag_match_push_once_per_window():
    """A field note whose tag appears in the tool call gets pushed once —
    labeled, then stays quiet for that window."""
    coach, _c = _coach()
    coach.facts.set_field_notes([
        {"id": 7, "text": "gobuster wants --timeout, not --max-time",
         "tags": ["gobuster", "enum"]}])
    _s, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "gobuster dir -u http://x"},
        proactive=True)
    assert "FIELD NOTE (unverified): gobuster wants --timeout" in res
    _s, res2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "gobuster dir -u http://y"},
        proactive=True)
    assert "FIELD NOTE" not in res2


async def test_field_note_hit_feedback_on_progress():
    """Pushed note + subsequent progress → lesson_hit(nid) fires once."""
    coach, c = _coach()
    coach.facts.set_field_notes([
        {"id": 9, "text": "n", "tags": ["ssh"]}])
    await coach._dispatch({"type": "exec_in_kali", "command": "ssh x"},
                         proactive=True)
    assert coach._notes_pushed.get(9) is not None
    coach.state.progress()          # a flag/checkpoint landed
    await coach._dispatch({"type": "exec_in_kali", "command": "id"},
                         proactive=True)
    await asyncio.sleep(0)
    assert c.hits == [9]
    assert 9 not in coach._notes_pushed


async def test_lookup_guide_union_searches_field_notes():
    """lookup_guide answers from modules AND unverified field notes — note
    appended under a module hit, note alone when no module matches."""
    coach, _c = _coach()
    coach.facts.set_field_notes([
        {"id": 3, "text": "app01 needs Bearer from config.js",
         "tags": ["app01", "bearer"]}])
    _s, res = await coach._dispatch(
        {"type": "lookup_guide", "query": "app01 bearer"},
        proactive=True)
    assert "FIELD NOTE" in res and "config.js" in res
    _s, res2 = await coach._dispatch(
        {"type": "lookup_guide", "query": "unrelated-zzz"},
        proactive=True)
    assert "FIELD NOTE" not in res2


async def test_cred_spray_note_after_two_failed_hosts():
    """A credential that auth-failed on ≥2 hosts is a scope fact — the
    agent gets ONE advisory per (secret,host) instead of learning nothing
    (s84: deploy/web01-pw sprayed across .31/.32/.33). Advisory only —
    password reuse on an untried host stays legitimate."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    c = coach.facts.add_cred("deploy", "Nw#Deploy!24", source="loot")
    c.tested_on.update({"web01", "10.1.10.31", "10.1.10.32"})
    c.valid_on.add("web01")
    # third distinct host with the same dead cred → advisory on the result
    _d, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'Nw#Deploy!24' ssh deploy@10.1.10.33 'id'"},
        proactive=True)
    assert "NOTE:" in res and "host-scoped" in res and "10.1.10.31" in res
    # pop-once: the same (secret,host) never nags twice — other NOTEs
    # (output dedup) may still fire, only the spray marker must not
    _d3, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'Nw#Deploy!24' ssh deploy@10.1.10.33 'id'"},
        proactive=True)
    assert "host-scoped" not in res
    # but a NEW host with the same cred still gets the scope warning
    _d2, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'Nw#Deploy!24' ssh deploy@10.1.10.34 'id'"},
        proactive=True)
    assert "NOTE:" in res and "host-scoped" in res
    # a cred with <2 prior failures → silent (reuse is fine)
    c2 = coach.facts.add_cred("root", "other-pw", source="loot")
    c2.tested_on.add("10.1.10.31")
    _d, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'other-pw' ssh root@10.1.10.35 'id'"},
        proactive=True)
    assert "host-scoped" not in res


async def test_turn_effort_threads_to_llm_call():
    """adaptive effort: chat replies run 'low', routine proactive turns
    'medium', stage-2 escalations keep 'high' — otherwise a local model
    burns the whole 600s turn budget thinking (s84: 3 cancels/h)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    llm = FakeLlm(actions=[{"type": "send_chat", "content": "hi"}])
    coach.llm = llm
    # chat answer → low effort
    await coach._llm_turn("reply", force_reply=True, effort="low")
    assert llm.kwargs[-1].get("reasoning_effort") == "low"
    # proactive stage-2 → deep (configured or 'high')
    await coach._llm_turn("work", proactive=True, effort="high")
    assert llm.kwargs[-1].get("reasoning_effort") == "high"


async def test_llm_client_per_call_effort_override():
    """chat(reasoning_effort=X) overrides the client default in the request
    body — the whole point of the per-turn adaptive mapping."""
    from coach.llm import LlmClient
    llm = LlmClient("http://x", "", "m", reasoning_effort="high")
    seen: list[dict] = []
    class _R:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"total_tokens": 1}}
    async def _post(path, json=None):
        seen.append(json or {})
        return _R()
    llm._client.post = _post          # type: ignore[attr-defined]
    await llm.chat([{"role": "user", "content": "x"}], json_mode=False,
                   reasoning_effort="low")
    assert seen[-1].get("reasoning_effort") == "low"
    # no override → client default wins
    await llm.chat([{"role": "user", "content": "x"}], json_mode=False)
    assert seen[-1].get("reasoning_effort") == "high"


async def test_lookup_guide_repeat_fetch_short_circuits():
    """Same module pulled twice by one window → 'already loaded' note
    instead of re-paying the body (s1: the .git module was fetched 5x
    in 18min by the same window). Dedup keys on the RESOLVED id, is
    per-window, and never blocks a different module."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    _, res1 = await coach._dispatch(
        {"type": "lookup_guide", "query": "git-leak"}, proactive=True)
    assert "zlib.decompress" in res1
    # different query, same resolved module → short-circuit
    _, res2 = await coach._dispatch(
        {"type": "lookup_guide", "query": "refs/heads"}, proactive=True)
    assert "already loaded" in res2 and "zlib.decompress" not in res2
    # a worker window gets its own first fetch — separate context
    _, res3 = await coach._dispatch(
        {"type": "lookup_guide", "query": "git-leak"},
        proactive=True, window="w1")
    assert "zlib.decompress" in res3
    # a different module still fetches on the main window
    _, res4 = await coach._dispatch(
        {"type": "lookup_guide", "query": "pivoting"}, proactive=True)
    assert "already loaded" not in res4 and "pivot" in res4.lower()


async def test_probe_commands_pass_missing_denials():
    """`which expect python3 perl` is a PROBE, not an invocation — a
    known missing:expect fact must not nuke the whole compound probe
    and lose the python3/perl availability info (s84 live)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials += ["missing:expect@kali", "missing:curl@web01"]
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "which expect python3 perl"}, proactive=True)
    assert did, res
    # probes in a remote tail stay free too
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'which curl wget'"},
        proactive=True)
    assert did, res
    # actual invocation still denied — local AND remote
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "expect -c 'spawn ssh app01'"}, proactive=True)
    assert not did and "missing:expect@kali" in res
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "ssh deploy@web01 'curl -s http://app01/'"},
        proactive=True)
    assert not did and "missing:curl@web01" in res
    # probe-then-invoke compound: the invocation still bites
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "which expect && expect -c 'send x'"}, proactive=True)
    assert not did and "missing:expect@kali" in res


async def test_literal_sshpass_var_gets_note():
    """`sshpass -p '$pass'` passes the literal text, not the variable —
    the following auth failure looks like a wrong cred although none
    was tried. The result must name the footgun (s1: cost a turn)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p '$pass' ssh deploy@web01 'id'"},
        proactive=True)
    assert did and "LITERAL" in res
    # a real password (no $) gets no note
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "sshpass -p 'Hun7er' ssh deploy@web01 'id'"},
        proactive=True)
    assert did and "LITERAL" not in res


async def test_worker_target_dup_advisory_once():
    """Main window execing against a target a RUNNING worker already
    covers → advisory note once (s1: main re-ran nmap -p- on app01
    while w2 owned that task). Advisory only — the exec still runs."""
    from coach.loop import _Worker
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach._workers["w2"] = _Worker(
        id="w2", task="nmap -p- app01 (10.1.10.33) for open ports",
        started=time.monotonic())
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -p- 10.1.10.33"}, proactive=True)
    assert did and "w2 is already working on 10.1.10.33" in res
    # second dup → silent (pop-once)
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -sV 10.1.10.33"}, proactive=True)
    assert did and "already working" not in res
    # a target no worker covers → no note
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -p- 10.1.10.32"}, proactive=True)
    assert did and "already working" not in res
    # worker execs on its own target are its JOB — no self-advisory
    did, res = await coach._dispatch(
        {"type": "exec_in_kali",
         "command": "nmap -p- 10.1.10.33"}, proactive=True, window="w2")
    assert did and "already working" not in res


async def test_resync_seeds_progress_clock():
    """resync() must treat started_at/ready_at as liveness: a session
    parked in 'ready' then activated must not look stuck-since-attach
    (s1 entered takeover at stage=2 instantly)."""
    from datetime import UTC, datetime
    started = datetime.now(UTC).isoformat()
    ctx = {**FakeClient().ctx,
           "session": {"id": 1, "state": "active", "autonomy_level": 4,
                       "coach_enabled": True, "started_at": started}}
    coach, c = _coach()
    c.ctx = ctx
    coach.state.last_progress_ts = 10.0   # stale attach-time clock
    await coach.resync()
    assert coach.state.last_progress_ts > 1000
    # and an OLDER started_at must never rewind real progress
    coach.state.last_progress_ts = time.time()
    await coach.resync()
    assert coach.state.last_progress_ts > 1000000


async def test_deep_effort_spent_once_per_stall_window():
    """stage>=2 spends deep effort ONCE per no-progress window — every-
    turn-deep burned the 600s budget in cancels (s84: 3/30min). New
    progress re-earns the depth; routine turns never spend it."""
    coach, _ = _coach({"coach": {"nudge_after_s": 10, "hint_after_s": 30,
                                 "effort_routine": "medium",
                                 "effort_deep": "high"},
                       "llm": {"reasoning_effort": "high"}})
    coach.llm = FakeLlm(actions=[{"type": "none"}])
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.state.last_progress_ts = time.time() - 5000   # deeply stuck
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(10)
    assert coach.llm.kwargs[-1].get("reasoning_effort") == "high"
    coach.state.last_nudge_ts = 0                       # cooldown hack
    await coach._reflect_tick(10)
    # spent — same stall window falls back to routine effort
    assert coach.llm.kwargs[-1].get("reasoning_effort") == "medium"
    coach.state.last_nudge_ts = 0
    coach.state.progress()                              # new evidence
    # the NEXT stall window (post-spend progress now long ago → stage
    # climbs back to >=2) re-earns the one deep turn
    coach.state.last_progress_ts = time.time() - 5000
    await coach._reflect_tick(10)
    assert coach.llm.kwargs[-1].get("reasoning_effort") == "high"


class QueueLlm(FakeLlm):
    """Sequential responses for worker-loop tests — items are resp dicts or
    the string 'CANCEL' to raise CancelledError mid-loop."""
    def __init__(self, seq):
        super().__init__()
        self.seq = list(seq)
        self.msgs_seen: list[list] = []

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        self.msgs_seen.append([m.get("content") for m in messages])
        item = self.seq.pop(0) if self.seq else {
            "content": "done", "actions": [{"type": "none"}],
            "tool_calls": [], "raw": {"usage": {}}, "reasoning": ""}
        if item == "CANCEL":
            raise asyncio.CancelledError()
        return item


def _exec_resp(cmd: str) -> dict:
    return {"content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "exec_in_kali",
                      "arguments": f'{{"command": "{cmd}"}}'}}],
        "actions": [{"type": "exec_in_kali", "command": cmd, "_call_id": "c1"}],
        "raw": {"usage": {}}, "reasoning": ""}


async def test_worker_done_note_reaches_parent_not_workers():
    """_finish_worker queues a completion note; the PARENT's next result
    carries it, a sibling worker's result must not eat it (s1: workers
    finished unnoticed — the parent never polled agent_status)."""
    from coach.loop import _Worker
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    w = _Worker(id="w1", task="scan web01", started=time.monotonic())
    w.status, w.report, w.actions = "done", "found port 80", 7
    coach._workers["w1"] = w
    await coach._finish_worker(w)
    assert coach._worker_done and "w1 done" in coach._worker_done[0]
    # a sibling worker's dispatch must NOT drain the parent notice
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "id"},
        proactive=True, window="w2")
    assert did and "WORKER DONE" not in res
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "whoami"}, proactive=True)
    assert "WORKER DONE" in res and "collect_agent(\"w1\")" in res


async def test_worker_parse_failure_retried_then_done():
    """A parse-failed first turn must NOT kill the worker — corrective
    retry, then normal work (s1: w1..w3 each died on their FIRST turn
    to 'no valid actions parsed')."""
    from coach.loop import _Worker
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = QueueLlm([
        {"content": "let me think...", "tool_calls": [],
         "actions": [{"type": "none", "reason": "no valid actions parsed"}],
         "raw": {"usage": {}}, "reasoning": ""},
        _exec_resp("id"),
        {"content": "report: nothing found", "tool_calls": [],
         "actions": [{"type": "none"}], "raw": {"usage": {}},
         "reasoning": ""},
    ])
    w = _Worker(id="w1", task="check id", started=time.monotonic())
    coach._workers["w1"] = w
    await coach._worker_loop(w)
    assert w.status == "done" and w.actions == 1
    assert any("id" == cmd for cmd, _w in c.exec_calls)
    # corrective message reached the model
    assert any("corrective" in str(m) for m in coach.llm.msgs_seen[-1])


async def test_worker_three_parse_failures_give_up():
    """The retry is bounded — three consecutive invalid turns end the
    worker with whatever content it produced."""
    from coach.loop import _Worker
    bad = {"content": "nope", "tool_calls": [],
           "actions": [{"type": "none", "reason": "no valid actions parsed"}],
           "raw": {"usage": {}}, "reasoning": ""}
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = QueueLlm([bad, bad, bad])
    w = _Worker(id="w1", task="x", started=time.monotonic())
    await coach._worker_loop(w)
    assert w.status == "done" and w.actions == 0
    assert len(coach.llm.calls) == 3  # initial + 2 retries, not infinite


async def test_worker_task_brief_survives_context_trim():
    """msgs[:1]+msgs[-29:] dropped the task brief after ~15 turns — the
    worker drifted off-task. The brief must be present in EVERY call."""
    from coach.loop import _Worker
    seq = [_exec_resp("id") for _ in range(18)]
    coach, _ = _coach({"coach": {"worker_turn_cap": 20,
                                 "worker_time_cap_s": 3600},
                       "llm": {}})
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = QueueLlm(seq)
    w = _Worker(id="w1", task="MY-UNIQUE-BRIEF-42", started=time.monotonic())
    coach._workers["w1"] = w
    await coach._worker_loop(w)
    last = coach.llm.msgs_seen[-1]
    assert any("MY-UNIQUE-BRIEF-42" in str(c) for c in last)


async def test_denial_note_is_per_window():
    """A new denial fact must reach EVERY window's guaranteed-read note —
    a shared _denial_seen let the first exec'ing agent eat it for all."""
    from coach.loop import _Worker
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach._workers["w1"] = _Worker(id="w1", task="t",
                                 started=time.monotonic())
    coach.facts.denials.append("filtered:9.9.9.9@kali")
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "id"},
        proactive=True, window="w1")
    assert did and "filtered:9.9.9.9@kali" in res  # worker sees it
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "whoami"}, proactive=True)
    assert did and "filtered:9.9.9.9@kali" in res  # parent sees it too


async def test_observer_hint_parent_window_only():
    """Observer advisories address the stuck parent — a worker's dispatch
    must not pop and hide them (found in subagent audit)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.state.pending_observer_hints.append("try the vault on :8080")
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "id"},
        proactive=True, window="w1")
    assert did and "OBSERVER" not in res
    assert coach.state.pending_observer_hints  # not eaten
    did, res = await coach._dispatch(
        {"type": "exec_in_kali", "command": "whoami"}, proactive=True)
    assert "OBSERVER (unverified): try the vault on :8080" in res


async def test_denied_repeat_escalates_and_hints_guide():
    """Identical denied cmd ×N escalates + the denial reason triggers
    the matching guide hint once (filtered → pivoting)."""
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.facts.denials.append("filtered:10.1.10.32@kali")
    did, res1 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "nmap -p- 10.1.10.32"},
        proactive=True)
    assert not did and "filtered:10.1.10.32@kali" in res1
    assert "pivoting" in res1          # guide hint fired on the denial
    did, res2 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "nmap -p- 10.1.10.32"},
        proactive=True)
    assert not did and "REPEATED ×2" in res2
    assert "pivoting" not in res2      # hint is once-per-module


async def test_killed_worker_merges_last_output():
    """kill_agent mid-work must not lose findings — the killed path
    synthesizes a report from last_out so _finish_worker merges it."""
    from coach.loop import _Worker
    coach, _ = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach.llm = QueueLlm([_exec_resp("id"), "CANCEL"])
    w = _Worker(id="w2", task="enum", started=time.monotonic())
    coach._workers["w2"] = w
    with pytest.raises(asyncio.CancelledError):
        await coach._worker_loop(w)
    assert w.status == "killed"
    assert "killed after" in w.report and "last output" in w.report
    assert coach._worker_done and "w2 killed" in coach._worker_done[0]


def test_effort_maps_to_template_kwargs():
    """LM Studio ignores top-level reasoning_effort (issue #2413) — the
    value must also be mirrored into chat_template_kwargs with the
    qwen3.8 value set (xhigh|medium|low), and 'low'/'off' must reach
    enable_thinking since that's the only lever that works there."""
    from coach.llm import LlmClient
    seen = {}
    class Probe:
        async def post(self, url, json=None, **kw):
            seen.update(json)
            class R:
                status_code = 200
                text = ""
                def raise_for_status(self): pass
                def json(self):
                    return {"choices": [{"message": {"content": "x"},
                                         "finish_reason": "stop"}],
                            "usage": {}}
            return R()
        async def aclose(self): pass
    import asyncio as aio
    cli = LlmClient("http://x", "", "m", reasoning=True,
                    reasoning_effort="high")
    cli._client = Probe()
    aio.run(cli.chat([{"role": "user", "content": "hi"}]))
    kw = seen["chat_template_kwargs"]
    assert kw["reasoning_effort"] == "xhigh"   # 'high' would raise in jinja
    cli2 = LlmClient("http://x", "", "m", reasoning=True,
                     reasoning_effort="low")
    cli2._client = Probe()
    seen.clear()
    aio.run(cli2.chat([{"role": "user", "content": "hi"}]))
    assert seen["chat_template_kwargs"]["enable_thinking"] is False
