"""Reaction-model regressions: telemetry stays silent, chat is debounced,
history/proactive-streak/welcome/vision behaviors."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

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

    async def exec_in_kali(self, sid, command):
        return {"out": "ok", "visible": True}

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

    # a chat-only proactive turn still counts toward the streak
    coach.llm = FakeLlm(actions=[{"type": "send_chat", "content": "nudge"}])
    coach.state.proactive_streak = 0
    coach.state.last_nudge_ts = 0
    await coach._reflect_tick(60)
    assert coach.state.proactive_streak == 1


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
    assert coach.state.commands[-1].from_coach


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
