"""Reaction-model regressions: telemetry stays silent, chat is debounced,
history/proactive-streak/welcome/vision behaviors."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
                           done=False, kind="chat"):
        pass

    async def send_activity(self, sid, text="", *, active=True):
        self.activities.append((active, text))

    async def exec_in_kali(self, sid, command):
        return {"out": "ok", "exitcode": 0, "visible": True}

    async def type_in_pane(self, sid, text):
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
    coach, c = _coach()
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
        async def exec_in_kali(self, sid, command):
            return {"out": "student@target01's password: ",
                    "err": "still running — pane is now busy",
                    "exitcode": None, "visible": True, "timed_out": True}
        async def type_in_pane(self, sid, text):
            self.typed = getattr(self, "typed", [])
            self.typed.append(text)
            # password accepted but the pane stays inside ssh — still busy
            return {"out": "student@target01:~$ ", "visible": True,
                    "busy": True}
    coach, c = _coach()
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
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.ctx["session"]["autonomy_level"] = 4
    coach._pane_interactive = True
    class ShellClient(FakeClient):
        async def type_in_pane(self, sid, text):
            return {"out": "root@kali:~# ", "visible": True, "busy": False}
    coach.client = ShellClient()
    did, res = await coach._dispatch(
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
        async def exec_in_kali(self, sid, command):
            return {"out": "21/tcp open  ftp\n22/tcp open  ssh",
                    "exitcode": 0, "visible": True}
    coach, c = _coach()
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
    _, r3 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "grep -i open /tmp/nmap.txt"},
        proactive=True)
    did, r4 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "head /tmp/nmap.txt"},
        proactive=True)
    assert not did and "denied" in r4 and "ALREADY_DONE" in r4
    # a different path still reads fine
    did, r5 = await coach._dispatch(
        {"type": "exec_in_kali", "command": "cat /etc/passwd"},
        proactive=True)
    assert did


async def test_flag_in_output_gets_submit_directive():
    """A pentrAIn{...} in exec output must trigger an immediate submit
    directive in the tool result — the model re-read flag files 3-4x to
    'confirm' them instead of submitting (observed live)."""
    class FlagClient(FakeClient):
        async def exec_in_kali(self, sid, command):
            return {"out": "intern\npentrAIn{abc123def456}", "exitcode": 0,
                    "visible": True}
    coach, c = _coach()
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
    coach._flags_submitted["pentrAIn{abc123def456}"] = False
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
    did, r2 = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{invented}"}, proactive=True)
    assert did and c.flags == ["pentrAIn{invented}"]
    # a flag that WAS seen in output submits without challenge
    coach._flags_seen["pentrAIn{real}"] = 1
    did, r3 = await coach._dispatch(
        {"type": "submit_flag", "value": "pentrAIn{real}"}, proactive=True)
    assert did and c.flags[-1] == "pentrAIn{real}"


async def test_activity_status_emitted_around_exec():
    """While exec_in_kali blocks in tmux the UI must show a live status —
    emitted before the call, always cleared when the dispatch loop ends."""
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.llm = FakeLlm(actions=[{"type": "exec_in_kali", "command": "nmap -sV 10.0.0.5"}])
    await coach._llm_turn("scan it", force_reply=True)
    starts = [t for a, t in c.activities if a]
    assert starts and "nmap" in starts[0]
    assert c.activities[-1] == (False, "")


async def test_activity_cleared_when_dispatch_raises():
    coach, c = _coach()
    coach.state.autonomy_level = 4
    coach.llm = FakeLlm(actions=[{"type": "exec_in_kali", "command": "id"}])

    async def boom(sid, cmd):
        raise RuntimeError("backend gone")
    c.exec_in_kali = boom
    with pytest.raises(RuntimeError):
        await coach._llm_turn("go", force_reply=True)
    assert c.activities[-1] == (False, "")


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
    c.exec_in_kali = lambda sid, cmd: _denied()
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
    c.exec_in_kali = lambda sid, cmd: _denied()
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
    coach, c = _coach()
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
    c.exec_results = [{"out": "boom", "exitcode": 1}]
    await coach._dispatch({"type": "exec_in_kali", "command": "python3 -u /root/solve.py"})
    coach._run_exits["/root/solve.py"] = 1        # dispatch recorded the failure
    _v, r = await coach._dispatch({"type": "exec_in_kali", "command": w})
    assert not r.startswith("denied:")


async def test_start_seeds_write_counts_from_replay():
    """Coach restart mid-session: replayed writes must seed _write_counts so
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
    assert coach._write_counts["/root/solve.py"] == 2
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
    from coach.prompts import build_context_msg
    import time
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
